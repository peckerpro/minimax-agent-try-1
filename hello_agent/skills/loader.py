"""SKILL.md loader — scans user + builtin directories, parses, caches.

The loader is the single source of truth for *what skills exist*. It
walks two roots in order:

1. `~/.hello_agent/skills/*.md`  (user-installed skills, win over builtins)
2. `hello_agent/skills/builtin/*.md`  (bundled skills)

User skills with the same `name` as a builtin replace the builtin (the
loader logs a warning at INFO level so the user can audit collisions).

The loader is lazy + cached: the first call to `load_skill(name)` /
`list_skills()` walks the filesystem; subsequent calls return from the
in-memory cache until `reload()` is invoked. `clear_cache()` is also
exposed for tests that mutate the home directory.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from hello_agent.core.logging import get_logger
from hello_agent.skills.models import (
    Skill,
    SkillError,
    SkillNotFoundError,
    SkillParseError,
    parse_skill_markdown,
)

_logger = get_logger(__name__)


# ----- Paths ----------------------------------------------------------------


def get_user_skills_dir() -> Path:
    """The user-installed SKILL.md directory: `$HELLO_AGENT_HOME/skills/`.

    Created lazily by `ensure_user_skills_dir()`; here we just return the
    path. If the directory doesn't exist yet, callers should treat it as
    empty (not an error — fresh installs have no user skills).
    """
    # Local import: `core.paths` itself is profile-aware, so we want to
    # resolve it at call time, not at module import time.
    from hello_agent.core.paths import get_hello_agent_home

    return get_hello_agent_home() / "skills"


def ensure_user_skills_dir() -> Path:
    """`get_user_skills_dir()` + mkdir(parents=True, exist_ok=True)."""
    d = get_user_skills_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_active_skills_dir() -> Path:
    """The per-session activation list directory.

    Skills "active" for a session are listed in
    `~/.hello_agent/skills/active/<session_id>.txt` — one name per line.

    This is a v0.2 Day 7 stub: the file-based format is simpler than a
    database and matches the per-session enable/disable patterns already
    in use by `hello_agent.tools.registry.ToolRegistry` (`_enabled` /
    `_disabled` sets are scoped per-instance, not on disk).
    """
    from hello_agent.core.paths import get_hello_agent_home

    return get_hello_agent_home() / "skills" / "active"


def get_builtin_skills_dir() -> Path:
    """The bundled skills directory shipped with the wheel."""
    return Path(__file__).resolve().parent / "builtin"


# ----- Loader ---------------------------------------------------------------


class SkillLoader:
    """Loads SKILL.md files from user + builtin roots.

    Stateless apart from an in-memory cache. Constructing a fresh loader
    is cheap (no I/O happens until the first `list_skills()` /
    `load_skill()` call).
    """

    def __init__(
        self,
        *,
        user_dir: Path | None = None,
        builtin_dir: Path | None = None,
    ) -> None:
        self._user_dir: Path | None = user_dir
        self._builtin_dir: Path | None = builtin_dir
        self._cache: dict[str, Skill] | None = None

    # --- discovery ----------------------------------------------------------

    def _resolve_user_dir(self) -> Path:
        return self._user_dir if self._user_dir is not None else get_user_skills_dir()

    def _resolve_builtin_dir(self) -> Path:
        return (
            self._builtin_dir if self._builtin_dir is not None else get_builtin_skills_dir()
        )

    def _scan(self) -> dict[str, Skill]:
        """Walk both roots, parse each *.md, return {name: Skill}."""
        result: dict[str, Skill] = {}

        # 1. Builtins first — user skills override.
        builtin_dir = self._resolve_builtin_dir()
        if builtin_dir.is_dir():
            for path in sorted(builtin_dir.glob("*.md")):
                try:
                    skill = self._parse_file(path, is_builtin=True)
                except SkillError as exc:
                    _logger.warning("builtin skill %s: %s — skipping", path.name, exc)
                    continue
                result[skill.name] = skill
        else:
            _logger.debug("builtin skills dir does not exist: %s", builtin_dir)

        # 2. User skills — override builtins on name collision.
        user_dir = self._resolve_user_dir()
        if user_dir.is_dir():
            for path in sorted(user_dir.glob("*.md")):
                try:
                    skill = self._parse_file(path, is_builtin=False)
                except SkillError as exc:
                    _logger.warning("user skill %s: %s — skipping", path.name, exc)
                    continue
                if skill.name in result and not result[skill.name].is_builtin:
                    # Two user skills collide (different filenames, same
                    # frontmatter.name). Keep the first, log a warning.
                    _logger.warning(
                        "user skill %s collides with already-loaded user skill %r — keeping first",
                        path,
                        skill.name,
                    )
                    continue
                if skill.name in result:
                    _logger.info(
                        "user skill %r overrides builtin (path=%s)",
                        skill.name,
                        path,
                    )
                result[skill.name] = skill
        else:
            _logger.debug("user skills dir does not exist: %s", user_dir)

        return result

    @staticmethod
    def _parse_file(path: Path, *, is_builtin: bool) -> Skill:
        """Read + parse a SKILL.md from disk. Raises `SkillError` on failure."""
        # `encoding="utf-8"` is explicit per PLW1514 (Windows cp1252 footgun).
        text = path.read_text(encoding="utf-8")
        skill = parse_skill_markdown(text, path=str(path.resolve()))
        skill.is_builtin = is_builtin
        return skill

    # --- public API ---------------------------------------------------------

    def list_skills(self, *, use_cache: bool = True) -> list[Skill]:
        """Return every loaded skill, sorted by name.

        First call walks the filesystem; subsequent calls return from the
        in-memory cache. Pass `use_cache=False` to force a rescan.
        """
        if use_cache and self._cache is not None:
            return [self._cache[k] for k in sorted(self._cache)]
        self._cache = self._scan()
        return [self._cache[k] for k in sorted(self._cache)]

    def load_skill(self, name: str, *, use_cache: bool = True) -> Skill:
        """Return the named skill. Raises `SkillNotFoundError` if missing.

        `use_cache=True` (default) returns the cached skill if we already
        scanned; `use_cache=False` forces a fresh filesystem walk first.
        """
        if use_cache and self._cache and name in self._cache:
            return self._cache[name]
        # list_skills populates self._cache as a side effect.
        self.list_skills(use_cache=use_cache)
        if not self._cache or name not in self._cache:
            have = sorted(self._cache.keys()) if self._cache else []
            raise SkillNotFoundError(
                f"skill {name!r} not found (have: {have})"
            )
        return self._cache[name]

    def reload(self) -> list[Skill]:
        """Drop the cache and rescan the filesystem. Returns the new list."""
        self._cache = None
        return self.list_skills(use_cache=False)

    def clear_cache(self) -> None:
        """Drop the cache without rescanning. Tests use this for isolation."""
        self._cache = None


# ----- Module-level singleton + convenience --------------------------------


_loader: SkillLoader | None = None


def get_loader() -> SkillLoader:
    """Return a process-wide `SkillLoader` (lazy-constructed)."""
    global _loader
    if _loader is None:
        _loader = SkillLoader()
    return _loader


def reset_loader() -> None:
    """Drop the module-level singleton + its cache. Test helper."""
    global _loader
    _loader = None


# Procedural API — what most callers actually use. These delegate to the
# module-level loader; tests can pass their own loader via the explicit
# functions or by patching `get_loader()`.


def list_skills(*, use_cache: bool = True) -> list[Skill]:
    """All loaded skills (sorted by name)."""
    return get_loader().list_skills(use_cache=use_cache)


def load_skill(name: str, *, use_cache: bool = True) -> Skill:
    """Look up a skill by `frontmatter.name`. Raises if missing."""
    return get_loader().load_skill(name, use_cache=use_cache)


def reload_skills() -> list[Skill]:
    """Drop the loader cache and rescan."""
    return get_loader().reload()


def get_skill_command_prompt(skill_name: str) -> str:
    """Return the user message to inject when `/<skill-name>` is invoked.

    This is the v0.1 / hermes-compatible API: the user types
    `/file_organize`, we wrap the SKILL.md body in a user message that
    tells the LLM to follow those instructions.

    The skill must be loaded by the registry (so its `tools` and
    `triggers` are honoured) but the prompt itself is just a Markdown
    body — the LLM gets the procedure and runs with it.
    """
    skill = load_skill(skill_name)
    return f"The user has invoked the `{skill.name}` skill. Follow its instructions:\n\n{skill.body}"


def install_skill(src_path: str | os.PathLike[str]) -> Path:
    """Copy a SKILL.md into the user skills directory.

    Returns the destination path. Validates that the source parses
    cleanly (so we never install a broken SKILL.md) and refuses to
    overwrite an existing file with the same frontmatter.name unless
    `force=True` is passed via env (`HELLO_AGENT_SKILL_FORCE_INSTALL=1`)
    — protects against accidental clobbering of a user-edited skill.
    """
    src = Path(src_path).expanduser().resolve()
    if not src.is_file():
        raise SkillNotFoundError(f"source file does not exist: {src}")
    if src.suffix.lower() != ".md":
        raise SkillParseError(f"source file must be .md, got {src.suffix!r} ({src})")

    # Parse first — refuse to install unparseable skills.
    try:
        text = src.read_text(encoding="utf-8")
        skill = parse_skill_markdown(text, path=str(src))
    except (SkillError, OSError) as exc:
        raise SkillParseError(f"failed to read or parse {src}: {exc}") from exc

    dest_dir = ensure_user_skills_dir()
    # Use the frontmatter.name as the canonical filename so a renamed
    # source doesn't shadow the install. Collision check is by name.
    dest = dest_dir / f"{skill.name}.md"
    if dest.exists():
        if not os.environ.get("HELLO_AGENT_SKILL_FORCE_INSTALL"):
            raise SkillParseError(
                f"skill {skill.name!r} already installed at {dest}; "
                f"set HELLO_AGENT_SKILL_FORCE_INSTALL=1 to overwrite"
            )
        _logger.warning("install_skill: overwriting existing %s", dest)

    dest.write_text(text, encoding="utf-8")
    # Drop the loader cache so the next list_skills() sees the new file.
    reset_loader()
    _logger.info("installed skill %r from %s -> %s", skill.name, src, dest)
    return dest


def skill_fingerprint(skill: Skill) -> str:
    """Stable SHA-256 fingerprint of a skill's source.

    Used by the registry's per-session activation list and by the Web UI
    to detect "skill content changed since activation".
    """
    h = hashlib.sha256()
    h.update(skill.path.encode("utf-8", errors="replace"))
    h.update(b"\0")
    h.update(skill.body.encode("utf-8", errors="replace"))
    return h.hexdigest()


__all__ = [
    "SkillLoader",
    "get_loader",
    "reset_loader",
    "list_skills",
    "load_skill",
    "reload_skills",
    "get_skill_command_prompt",
    "install_skill",
    "skill_fingerprint",
    "get_user_skills_dir",
    "ensure_user_skills_dir",
    "get_active_skills_dir",
    "get_builtin_skills_dir",
]
