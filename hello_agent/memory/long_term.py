"""Long-term memory — SQLite-backed fact store.

Per the Day-4 spec (ENGINEERING.md §6.6), the public surface is:

- A `facts(id, key, value, source, created_at, updated_at)` table, where
  `id` is an autoincrement integer, `key` is the fact name, `value` is
  the fact body (stored as TEXT, JSON-encoded for structured values), and
  the timestamps are ISO-8601 UTC strings.
- `LongTermMemory` class wrapping the connection.
- `set_fact(key, value, source)` upserts a fact. When an Obsidian vault
  is configured, also writes a corresponding `.md` file with YAML
  frontmatter so the fact is visible in Obsidian Desktop and pushed to
  the GitHub mirror via the background `GitSync` thread.
- `get_fact(key)` returns the fact body (decoded if JSON), or `None`.
- `delete_fact(key)` removes a fact.
- `list_facts(source=...)` enumerates all facts (optionally filtered).
- `search(query)` substring search across key+value (FTS-like fallback).
- `reconcile_with_vault()` scans the Obsidian vault and updates this
  SQLite cache with any facts the agent doesn't know about (or that
  the user has edited in Obsidian Desktop). The vault is the source of
  truth; the SQLite table is a derived index for fast lookups.

Path resolution: the SQLite file is at `<HELLO_AGENT_HOME>/memory/long_term.db`
by default. The path is overridable via the constructor (useful for tests
that want a temp file) and via `config.memory.long_term.db_path`.

The implementation uses stdlib `sqlite3` (no ORM) and WAL journaling for
concurrent-reader friendliness. The connection is opened lazily on first
use and closed on `close()`.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hello_agent.core.logging import get_logger

logger = get_logger(__name__)

_DEFAULT_DB_PATH = "memory/long_term.db"


def _default_db_path() -> Path:
    """Resolve the default long-term db path under $HELLO_AGENT_HOME."""
    try:
        from hello_agent.core.config import get_config
        from hello_agent.core.paths import get_hello_agent_home

        cfg = get_config()
        rel = getattr(cfg.memory.long_term, "db_path", _DEFAULT_DB_PATH)
        rel_str = str(rel) if rel else _DEFAULT_DB_PATH
        # If the user gave a relative path, anchor it at the home dir.
        path = Path(rel_str)
        if not path.is_absolute():
            path = get_hello_agent_home() / rel_str
        return path
    except Exception:  # noqa: BLE001
        # Fall back to ~/.hello-agent/memory/long_term.db
        from hello_agent.core.paths import get_hello_agent_home

        return get_hello_agent_home() / "memory" / "long_term.db"


def _now_iso() -> str:
    """UTC ISO-8601 timestamp with second precision."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _encode_value(value: Any) -> str:
    """Encode a Python value for storage. Always JSON — even strings.

    Why: if we stored a string like `"1"` raw, `json.loads("1")` would
    return int 1 on the way back, silently corrupting the value. Always
    round-tripping through `json.dumps` keeps the type honest.
    """
    return json.dumps(value, ensure_ascii=False, default=str)


def _decode_value(blob: str) -> Any:
    """Inverse of `_encode_value`; falls back to raw string on JSON failure.

    Also handles the pre-Day-4 format where strings were stored raw
    (i.e. not JSON-quoted). If `json.loads` returns a non-string but the
    blob was a string, we return the blob as-is.
    """
    if blob is None:
        return None
    try:
        return json.loads(blob)
    except (ValueError, TypeError):
        return blob


class LongTermMemory:
    """SQLite-backed key-value fact store.

    Usage:
        mem = LongTermMemory()                # uses $HELLO_AGENT_HOME default
        mem.set_fact("favorite_editor", "vscode", source="user")
        v = mem.get_fact("favorite_editor")   # -> "vscode"
        mem.delete_fact("favorite_editor")
        mem.close()
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS facts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        key         TEXT NOT NULL,
        value       TEXT NOT NULL,
        source      TEXT NOT NULL DEFAULT 'unknown',
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL,
        UNIQUE(key)
    );
    CREATE INDEX IF NOT EXISTS idx_facts_source ON facts(source);
    CREATE INDEX IF NOT EXISTS idx_facts_key    ON facts(key);
    """

    __slots__ = (
        "db_path",
        "_conn",
        "_auto_reconcile",
        "_vault_reconciled",
        "_vault_path_override",
    )

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        auto_reconcile: bool = True,
        vault_path: str | Path | None = None,
    ) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        # Lazy vault → SQLite reconcile on first read. Tests can pass
        # `auto_reconcile=False` to skip the reconcile scan.
        self._auto_reconcile: bool = bool(auto_reconcile)
        self._vault_reconciled: bool = False
        # If set, override the config-derived vault path. Useful for
        # tests that want a temp vault; in production this stays None
        # and the global config is consulted.
        self._vault_path_override: str | Path | None = vault_path

    # --- connection management ------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            # WAL: many readers + one writer don't block each other.
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._conn.executescript(self.SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager that yields a connection inside an explicit txn."""
        conn = self._get_conn()
        conn.execute("BEGIN")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def __enter__(self) -> LongTermMemory:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- CRUD ------------------------------------------------------------

    def set_fact(
        self,
        key: str,
        value: Any,
        *,
        source: str = "unknown",
        mirror_to_vault: bool = True,
    ) -> int:
        """Upsert a fact. Returns the row id.

        When `mirror_to_vault=True` (the default) AND the user has set
        `OBSIDIAN_VAULT_PATH`, also writes a corresponding `.md` file
        to the vault's `memory/` subdir so the fact is visible in
        Obsidian Desktop and will be pushed to the GitHub mirror by
        the background `GitSync` thread.

        Pass `mirror_to_vault=False` to skip the vault write — useful
        when reconciling from the vault (avoids feedback loops) or in
        tests that don't want disk I/O.
        """
        if not key:
            raise ValueError("fact key must be a non-empty string")
        conn = self._get_conn()
        now = _now_iso()
        encoded = _encode_value(value)
        cur = conn.execute(
            """
            INSERT INTO facts (key, value, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                source     = excluded.source,
                updated_at = excluded.updated_at
            """,
            (key, encoded, source, now, now),
        )
        # lastrowid is the new or existing row id; for UPSERT SQLite
        # populates it correctly on insert. For updates we need to
        # follow up with a SELECT to get the id.
        row_id = cur.lastrowid
        if row_id is None or row_id == 0:
            row = conn.execute("SELECT id FROM facts WHERE key = ?", (key,)).fetchone()
            row_id = int(row["id"]) if row else 0

        # Write-through to the Obsidian vault (no-op when not configured).
        if mirror_to_vault:
            self._mirror_to_vault(key=key, value=value, source=source)

        return int(row_id or 0)

    def _mirror_to_vault(self, *, key: str, value: Any, source: str) -> str | None:
        """If the Obsidian vault is configured, write a `.md` for this fact.

        The body is the JSON-encoded value (or the raw string for string
        facts), with the source as a tag. The markdown uses YAML
        frontmatter that `ObsidianSync.export_memory` already produces —
        we go through `ObsidianSync` to keep the on-disk format
        consistent (single source of formatting truth).
        """
        try:
            from hello_agent.memory.obsidian_sync import ObsidianSync  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            return None
        # Honor the per-instance override (set in tests) before falling
        # back to the config-derived vault.
        sync = ObsidianSync(vault_path=self._vault_path_override)
        if not sync.is_configured():
            return None
        if isinstance(value, str):
            body = value
        else:
            body = json.dumps(value, ensure_ascii=False, indent=2)
        tags = [source] if source and source != "unknown" else None
        return sync.export_memory(
            memory_id=key,
            content=body,
            kind="fact",
            title=key.replace("_", " ").title(),
            tags=tags,
        )

    # --- vault → SQLite reconciliation ----------------------------------
    #
    # The Obsidian vault is the source of truth for facts (the user can
    # edit / add / delete files in Obsidian Desktop). The SQLite table
    # is a derived index for fast lookups. `reconcile_with_vault()` is
    # the one-way sync from vault → SQLite; it never writes back to the
    # vault (so we don't fight the user's manual edits).
    #
    # In normal operation, `reconcile_with_vault()` is called lazily on
    # the first read of a `LongTermMemory` instance (gated by
    # `auto_reconcile=True`, the default). Tests can disable this by
    # passing `auto_reconcile=False`. The CLI exposes a manual
    # `hello-agent memory reconcile` command for explicit runs.

    def _maybe_reconcile(self) -> None:
        """Lazy one-shot reconcile on the first read in a session."""
        if not self._auto_reconcile or self._vault_reconciled:
            return
        self._vault_reconciled = True
        try:
            result = self.reconcile_with_vault()
            if result.get("added", 0) or result.get("updated", 0):
                logger.bind(category="memory").info(
                    "long_term reconciled from vault: {}", result
                )
        except Exception as exc:  # noqa: BLE001 — never break the read path
            logger.bind(category="memory").debug(
                "long_term reconcile skipped: {}", exc
            )

    def reconcile_with_vault(self) -> dict[str, Any]:
        """Scan the Obsidian vault and update this SQLite cache.

        Returns a status dict with keys:

        - `configured`: bool — whether the vault is set
        - `added`: int — facts added to SQLite
        - `updated`: int — facts whose SQLite value was overwritten by vault
        - `skipped`: int — facts already in sync
        - `reason`: str — present only when not configured / errored

        Vault wins on conflict (the user can edit files in Obsidian).
        New facts (a `.md` with a frontmatter `id` that doesn't exist
        in SQLite) are added with `source="vault"`.
        """
        try:
            from hello_agent.memory.obsidian_sync import ObsidianSync  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            return {"configured": False, "added": 0, "updated": 0, "skipped": 0,
                    "reason": "obsidian_sync not importable"}

        # Honor the per-instance override (set in tests) before falling
        # back to the config-derived vault.
        sync = ObsidianSync(vault_path=self._vault_path_override)
        if not sync.is_configured():
            return {"configured": False, "added": 0, "updated": 0, "skipped": 0,
                    "reason": "OBSIDIAN_VAULT_PATH is not set"}

        added = 0
        updated = 0
        skipped = 0
        try:
            memories = sync.list_memories()
        except Exception as exc:  # noqa: BLE001
            return {"configured": True, "added": 0, "updated": 0, "skipped": 0,
                    "reason": f"list_memories failed: {exc}"}

        for mem in memories:
            key = str(mem.get("id") or "").strip()
            if not key:
                skipped += 1
                continue
            record = sync.get_memory(key)
            if record is None:
                skipped += 1
                continue
            body = (record.get("content") or "").strip()
            # Body is the raw markdown body. For string facts, the user
            # (or the export) wrote a plain string; for structured
            # values, the body is JSON. Try JSON first, fall back to raw.
            if not body:
                value: Any = ""
            else:
                try:
                    value = json.loads(body)
                except (ValueError, TypeError):
                    value = body

            existing = self.get_fact_row(key)
            if existing is None:
                self.set_fact(key, value, source="vault", mirror_to_vault=False)
                added += 1
            elif existing["value"] != value:
                # Vault wins: overwrite SQLite. Use `source="vault"` to
                # mark the row as vault-derived (visible via list_facts).
                self.set_fact(key, value, source="vault", mirror_to_vault=False)
                updated += 1
            else:
                skipped += 1

        return {"configured": True, "added": added, "updated": updated, "skipped": skipped}

    def get_fact(self, key: str, default: Any = None) -> Any:
        """Return the fact body (decoded) or `default` if missing."""
        self._maybe_reconcile()
        row = self._get_conn().execute(
            "SELECT value FROM facts WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return _decode_value(row["value"])

    def get_fact_row(self, key: str) -> dict[str, Any] | None:
        """Return the full row (id, key, value, source, timestamps)."""
        self._maybe_reconcile()
        row = self._get_conn().execute(
            "SELECT id, key, value, source, created_at, updated_at FROM facts WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "key": row["key"],
            "value": _decode_value(row["value"]),
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def delete_fact(self, key: str) -> bool:
        """Remove a fact. Returns True iff a row was actually deleted."""
        cur = self._get_conn().execute("DELETE FROM facts WHERE key = ?", (key,))
        return cur.rowcount > 0

    def list_facts(self, *, source: str | None = None) -> list[dict[str, Any]]:
        """List all facts (optionally filtered by `source`)."""
        self._maybe_reconcile()
        if source is None:
            rows = self._get_conn().execute(
                "SELECT id, key, value, source, created_at, updated_at "
                "FROM facts ORDER BY id"
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT id, key, value, source, created_at, updated_at "
                "FROM facts WHERE source = ? ORDER BY id",
                (source,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "key": r["key"],
                "value": _decode_value(r["value"]),
                "source": r["source"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        """Substring search across `key` and `value`.

        Case-insensitive LIKE match. For full FTS5 support, see §7.3 (deferred).
        """
        self._maybe_reconcile()
        if not query:
            return []
        like = f"%{query}%"
        rows = self._get_conn().execute(
            "SELECT id, key, value, source, created_at, updated_at "
            "FROM facts WHERE key LIKE ? OR value LIKE ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (like, like, int(limit)),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "key": r["key"],
                "value": _decode_value(r["value"]),
                "source": r["source"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def count(self, *, source: str | None = None) -> int:
        self._maybe_reconcile()
        if source is None:
            row = self._get_conn().execute("SELECT COUNT(*) AS n FROM facts").fetchone()
        else:
            row = self._get_conn().execute(
                "SELECT COUNT(*) AS n FROM facts WHERE source = ?", (source,)
            ).fetchone()
        return int(row["n"]) if row else 0
