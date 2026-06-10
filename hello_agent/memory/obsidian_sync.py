"""Obsidian vault sync — serialize memories as markdown with frontmatter.

Implements the spec from ENGINEERING.md §7.3.

Key design points:

- If `OBSIDIAN_VAULT_PATH` is empty (the default), every public method
  is a no-op that returns safely. This is the "scaffold" behavior: the
  feature is fully wired into the code, but it doesn't *do* anything
  until the user opts in by setting the env var. The CLI shows a
  one-line warning so the user knows what's happening.

- The output format is Obsidian-compatible: YAML frontmatter with
  `id`, `kind`, `created`, `tags`, `source_session`, plus a `# Title`
  heading and a `## Related` section listing wikilinks.

- We use `python-frontmatter==1.1.0` (already in core dependencies).

- Wikilinks `[[like this]]` and inline `#tags` are auto-extracted from
  the content body and merged with the user-supplied tags.

Filename format: `<YYYY-MM-DD>_<slug>.md`, where the slug is a
filesystem-safe version of the memory id.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hello_agent.core.config import get_config
from hello_agent.core.logging import get_logger

logger = get_logger(__name__)


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z0-9_/-]+)")
_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _vault_is_configured() -> bool:
    """True if the user has set `OBSIDIAN_VAULT_PATH` (or config)."""
    try:
        cfg = get_config()
        return bool(cfg.memory.obsidian_vault_path)
    except Exception:  # noqa: BLE001
        return False


def _vault_path() -> Path:
    cfg = get_config()
    vp = cfg.memory.obsidian_vault_path
    assert vp is not None  # caller must check _vault_is_configured first
    return Path(vp).expanduser().resolve()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slugify(text: str, max_len: int = 50) -> str:
    """Filesystem-safe slug. Mirrors the spec's 50-char cap."""
    s = text.lower().strip()
    s = _SLUG_RE.sub("-", s)
    s = s.strip("-")
    return (s or "memory")[:max_len]


class ObsidianSync:
    """Markdown-with-frontmatter serializer for the user's memory vault.

    The class is safe to instantiate when no vault is configured — every
    public method will return a sentinel value (`None` for `get_memory`,
    empty list for `list_memories`, the memory_id unchanged for
    `export_memory`) and log a one-line notice.
    """

    def __init__(
        self,
        vault_path: str | Path | None = None,
        memory_subdir: str = "memory",
    ) -> None:
        self._memory_subdir: str = memory_subdir
        self._explicit_vault: Path | None = (
            Path(vault_path).expanduser().resolve() if vault_path else None
        )
        self._last_export: dict[str, str] = {}

    # --- internals --------------------------------------------------------

    def _resolve_vault(self) -> Path | None:
        if self._explicit_vault is not None:
            return self._explicit_vault
        if not _vault_is_configured():
            return None
        return _vault_path()

    def _memory_dir(self, vault: Path) -> Path:
        d = vault / self._memory_subdir
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _find_existing_memory_file(self, vault: Path, memory_id: str) -> Path | None:
        """Look for an existing `.md` in the memory dir whose frontmatter id matches.

        Returns the path if found, else None. Used by `export_memory` to
        keep filenames stable across re-exports on different days.
        """
        try:
            import frontmatter  # type: ignore[import-not-found]  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            return None
        for fp in self._memory_dir(vault).glob("*.md"):
            try:
                post = frontmatter.load(fp)
            except Exception:  # noqa: BLE001
                continue
            if post.get("id") == memory_id:
                return fp
        return None

    def _disabled_log(self, op: str) -> None:
        logger.bind(category="memory").info(
            "obsidian_sync.{}: no-op (OBSIDIAN_VAULT_PATH is not set)", op
        )

    # --- public API -------------------------------------------------------

    def export_memory(
        self,
        memory_id: str,
        content: str,
        *,
        kind: str = "fact",
        title: str | None = None,
        tags: list[str] | None = None,
        related: list[str] | None = None,
        source_session_id: str | None = None,
    ) -> str | None:
        """Write a memory to the vault. Returns the file path or None.

        See the module docstring for the file format.
        """
        vault = self._resolve_vault()
        if vault is None:
            self._disabled_log("export_memory")
            return None

        # Lazy import — python-frontmatter is in core deps but we keep the
        # check defensive in case someone unpins it.
        try:
            import frontmatter  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "python-frontmatter is required for ObsidianSync — install with "
                "`uv add python-frontmatter`"
            ) from exc

        title = title or memory_id.replace("_", " ").title()
        tags = list(tags or [])
        related = list(related or [])

        # Extract inline wikilinks and tags from the content body.
        inline_links = WIKILINK_RE.findall(content)
        inline_tags = TAG_RE.findall(content)
        all_tags = sorted(set(tags + inline_tags))
        all_links = sorted(set(related + inline_links))

        post = frontmatter.Post(content)
        post["id"] = memory_id
        post["kind"] = kind
        post["created"] = _now_iso()
        post["tags"] = all_tags
        post["source_session"] = source_session_id
        post["title"] = title

        if all_links:
            post.content = (
                post.content.rstrip()
                + "\n\n## Related\n"
                + "\n".join(f"- [[{link}]]" for link in all_links)
                + "\n"
            )

        slug = _slugify(memory_id)
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        # Look for an existing .md with the same frontmatter `id` so
        # re-exports on later days overwrite the original file in place
        # instead of creating a duplicate. The filename is stable for
        # the lifetime of the memory; the frontmatter `created` is the
        # true creation timestamp.
        existing_path = self._find_existing_memory_file(vault, memory_id)
        file_path = existing_path or self._memory_dir(vault) / f"{date_str}_{slug}.md"
        file_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        self._last_export[memory_id] = str(file_path)
        logger.bind(category="memory").info(
            "exported memory {} -> {}", memory_id, file_path
        )
        return str(file_path)

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory file from the vault. Returns True if a file was removed."""
        vault = self._resolve_vault()
        if vault is None:
            self._disabled_log("delete_memory")
            return False
        path = self._last_export.get(memory_id)
        if path and Path(path).exists():
            Path(path).unlink()
            del self._last_export[memory_id]
            return True
        # Also search the memory dir for a file whose frontmatter id matches.
        try:
            import frontmatter  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return False
        for fp in self._memory_dir(vault).glob("*.md"):
            try:
                post = frontmatter.load(fp)
            except Exception:  # noqa: BLE001
                continue
            if post.get("id") == memory_id:
                fp.unlink()
                if memory_id in self._last_export:
                    del self._last_export[memory_id]
                return True
        return False

    def list_memories(self) -> list[dict[str, Any]]:
        """List all memory files in the vault. Returns a list of dicts."""
        vault = self._resolve_vault()
        if vault is None:
            self._disabled_log("list_memories")
            return []
        try:
            import frontmatter  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return []
        memories: list[dict[str, Any]] = []
        for fp in self._memory_dir(vault).glob("*.md"):
            try:
                post = frontmatter.load(fp)
            except Exception:  # noqa: BLE001
                continue
            memories.append(
                {
                    "path": str(fp),
                    "id": post.get("id", fp.stem),
                    "kind": post.get("kind", "unknown"),
                    "title": post.get("title", fp.stem),
                    "tags": list(post.get("tags", []) or []),
                }
            )
        return memories

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        """Look up a single memory by id. Returns the full record (or None)."""
        vault = self._resolve_vault()
        if vault is None:
            self._disabled_log("get_memory")
            return None
        try:
            import frontmatter  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return None
        for fp in self._memory_dir(vault).glob("*.md"):
            try:
                post = frontmatter.load(fp)
            except Exception:  # noqa: BLE001
                continue
            if post.get("id") == memory_id:
                return {
                    "path": str(fp),
                    "frontmatter": dict(post.metadata),
                    "content": post.content,
                }
        return None

    def extract_relations(self) -> dict[str, list[str]]:
        """Scan all memory files, return `{memory_id: [related_ids]}`.

        Powers the wikilink graph view both in-app and in Obsidian itself.
        """
        vault = self._resolve_vault()
        if vault is None:
            self._disabled_log("extract_relations")
            return {}
        try:
            import frontmatter  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return {}
        relations: dict[str, list[str]] = defaultdict(list)
        for fp in self._memory_dir(vault).glob("*.md"):
            try:
                post = frontmatter.load(fp)
            except Exception:  # noqa: BLE001
                continue
            mid = str(post.get("id", fp.stem))
            wikilinks = WIKILINK_RE.findall(post.content)
            if wikilinks:
                relations[mid] = sorted(set(wikilinks))
        return dict(relations)

    # --- introspection helpers (used by tests + CLI) ----------------------

    @property
    def last_export(self) -> dict[str, str]:
        """Read-only view of {memory_id: exported_path} for this session."""
        return dict(self._last_export)

    def is_configured(self) -> bool:
        """True iff the vault path is set (env or config)."""
        return self._resolve_vault() is not None

    def wallclock_now(self) -> float:
        """Helper for tests that need to monkeypatch time."""
        return time.time()
