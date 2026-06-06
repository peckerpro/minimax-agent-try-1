"""Episodic memory — past task summaries.

Per the Day-4 spec (ENGINEERING.md §6.6), `episodic.py` is a list of past
session summaries used for cross-session recall. The schema is:

    episodes(id, session_id, summary, created_at)

Where `id` is autoincrement, `session_id` is the originating session,
`summary` is a 1-3 sentence text body, and `created_at` is the UTC
timestamp when the episode was recorded.

The Day-4 trigger is `summarize_every_n_turns=20` (from `config.yaml`
`memory.episodic.summarize_every_n_turns`); every N turns the agent
loop should call `record_episode(session_id, summary)`.

`EpisodicMemory` is a thin SQLite wrapper analogous to `LongTermMemory`
— same conventions (lazy connection, WAL, context manager, close()).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_DB_PATH = "memory/long_term.db"  # share the long-term sqlite file
_SUMMARIZE_EVERY_N_TURNS_DEFAULT = 20


def _default_db_path() -> Path:
    """Share the long-term db file by default — it's all the user's persistent
    state, and we don't want a second sqlite handle to fight over locks."""
    try:
        from hello_agent.core.config import get_config
        from hello_agent.core.paths import get_hello_agent_home

        cfg = get_config()
        rel = getattr(cfg.memory.long_term, "db_path", _DEFAULT_DB_PATH)
        rel_str = str(rel) if rel else _DEFAULT_DB_PATH
        path = Path(rel_str)
        if not path.is_absolute():
            path = get_hello_agent_home() / rel_str
        return path
    except Exception:  # noqa: BLE001
        from hello_agent.core.paths import get_hello_agent_home

        return get_hello_agent_home() / "memory" / "long_term.db"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _summarize_every_n_turns() -> int:
    """Read `memory.episodic_summarize_every_n_turns` from config; default 20."""
    try:
        from hello_agent.core.config import get_config

        n = int(get_config().memory.episodic_summarize_every_n_turns)
        return n if n > 0 else _SUMMARIZE_EVERY_N_TURNS_DEFAULT
    except Exception:  # noqa: BLE001
        return _SUMMARIZE_EVERY_N_TURNS_DEFAULT


class EpisodicMemory:
    """SQLite-backed episode log.

    Usage:
        ep = EpisodicMemory()
        ep.record_episode(session_id="sess-1", summary="helped user write a poem")
        recent = ep.list_recent(limit=5)
        ep.close()
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS episodes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT NOT NULL,
        summary     TEXT NOT NULL,
        created_at  TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_episodes_session  ON episodes(session_id);
    CREATE INDEX IF NOT EXISTS idx_episodes_created  ON episodes(created_at);
    """

    __slots__ = ("db_path", "_conn", "summarize_every_n_turns")

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        summarize_every_n_turns: int | None = None,
    ) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.summarize_every_n_turns: int = (
            summarize_every_n_turns
            if summarize_every_n_turns is not None
            else _summarize_every_n_turns()
        )
        self._conn: sqlite3.Connection | None = None

    # --- connection management ------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.executescript(self.SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._get_conn()
        conn.execute("BEGIN")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")

    def __enter__(self) -> EpisodicMemory:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- CRUD ------------------------------------------------------------

    def record_episode(self, session_id: str, summary: str) -> int:
        """Append an episode. Returns the new row id."""
        if not session_id:
            raise ValueError("session_id must be a non-empty string")
        if not summary:
            raise ValueError("summary must be a non-empty string")
        cur = self._get_conn().execute(
            "INSERT INTO episodes (session_id, summary, created_at) VALUES (?, ?, ?)",
            (session_id, summary, _now_iso()),
        )
        return int(cur.lastrowid or 0)

    def list_recent(self, *, limit: int = 20, session_id: str | None = None) -> list[dict[str, str]]:
        """Return the most-recent episodes (optionally filtered to one session)."""
        if session_id is None:
            rows = self._get_conn().execute(
                "SELECT id, session_id, summary, created_at FROM episodes "
                "ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        else:
            rows = self._get_conn().execute(
                "SELECT id, session_id, summary, created_at FROM episodes "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, int(limit)),
            ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "session_id": r["session_id"],
                "summary": r["summary"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def search(self, query: str, *, limit: int = 20) -> list[dict[str, str]]:
        """Substring search across the summary field (case-insensitive)."""
        if not query:
            return []
        like = f"%{query}%"
        rows = self._get_conn().execute(
            "SELECT id, session_id, summary, created_at FROM episodes "
            "WHERE summary LIKE ? ORDER BY id DESC LIMIT ?",
            (like, int(limit)),
        ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "session_id": r["session_id"],
                "summary": r["summary"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def count(self, *, session_id: str | None = None) -> int:
        if session_id is None:
            row = self._get_conn().execute("SELECT COUNT(*) AS n FROM episodes").fetchone()
        else:
            row = self._get_conn().execute(
                "SELECT COUNT(*) AS n FROM episodes WHERE session_id = ?", (session_id,)
            ).fetchone()
        return int(row["n"]) if row else 0

    def should_summarize(self, turn_count: int) -> bool:
        """Day-4 trigger: `turn_count % summarize_every_n_turns == 0`.

        Returns False when `turn_count <= 0` or `summarize_every_n_turns <= 0`
        (which would mean "never summarize" — v0.1 disables it).
        """
        if self.summarize_every_n_turns <= 0 or turn_count <= 0:
            return False
        return turn_count % self.summarize_every_n_turns == 0
