"""Skills registry — trigger matching + per-session activation.

The registry is the runtime side of the skills system: it knows which
skills are loaded (via the loader), which skills are active for a given
session, and how to match a user prompt against a skill's triggers.

Three jobs, in order of how often they're called:

1. **`match(user_prompt)`** — given a user prompt, return the best
   matching `Skill` (or `None`). Trigger matching is regex-first
   (`triggers.regex`), then keyword fallback (`triggers.keywords`).
   Order is determined by Skill name for determinism; the first
   match wins.

2. **`activate_for_session(skill_name, session_id)` / `deactivate_for_session(...)`**
   — write/remove a name from
   `~/.hello_agent/skills/active/<session_id>.txt`. The agent reads
   the active list before each LLM call to build the
   `<available_skills>` block of the system prompt.

3. **`build_available_skills_block(session_id)`** — return the
   `<available_skills>...</available_skills>` markdown that the
   ReAct agent injects into its system prompt. This is the
   hermes-compatible v0.1 contract: the LLM sees a list of
   `(name, description)` pairs and the procedure for the matched
   skill when relevant.

The registry is a thin coordinator — all disk I/O for SKILL.md
parsing lives in `loader.py`. Keeping the split means the loader
can be tested in isolation (no sessions, no prompts) and the
registry can be tested with mock skills (no files).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from hello_agent.core.logging import get_logger
from hello_agent.skills.loader import (
    get_active_skills_dir,
    get_loader,
    list_skills,
    load_skill,
)
from hello_agent.skills.models import Skill, SkillError, SkillNotFoundError

_logger = get_logger(__name__)


# ----- Match result ---------------------------------------------------------


@dataclass(frozen=True)
class SkillMatch:
    """A `match()` result: the matched skill + which trigger fired + how.

    `trigger_kind` is `"regex"`, `"keyword"`, or `"name"` (for the
    case where the user typed `/skill_name` and we short-circuit).
    `trigger_text` is the literal regex pattern or keyword that
    matched (useful for logging + debugging).
    """

    skill: Skill
    trigger_kind: str
    trigger_text: str
    score: float = 1.0  # higher = better; reserved for future ranking

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return f"SkillMatch(name={self.skill.name!r}, kind={self.trigger_kind!r})"


# ----- Errors ---------------------------------------------------------------


class RegistryError(SkillError):
    """Base error for registry-level failures."""


class SkillActivationError(RegistryError):
    """`activate_for_session()` could not update the activation file."""


# ----- SkillRegistry --------------------------------------------------------


class SkillRegistry:
    """Runtime skill matching + per-session activation.

    Stateless apart from a back-reference to a loader. Constructing
    one is cheap; the heavy I/O is in the loader.
    """

    def __init__(self, loader=None) -> None:
        self._loader = loader if loader is not None else get_loader()
        # Cache compiled regexes by Skill so we don't recompile on every
        # prompt. Keyed by (name, regex_pattern) to invalidate if the
        # loader re-reads a SKILL.md and the pattern list changes.
        self._regex_cache: dict[tuple[str, str], re.Pattern[str]] = {}

    # --- matching ------------------------------------------------------------

    def _get_compiled(self, skill: Skill, pattern: str) -> re.Pattern[str]:
        key = (skill.name, pattern)
        compiled = self._regex_cache.get(key)
        if compiled is None:
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                _logger.warning(
                    "skill %r: invalid regex %r (%s) — skipping", skill.name, pattern, exc
                )
                # Fall back to a never-matches pattern so the loop keeps going.
                compiled = re.compile(r"(?!)")
            self._regex_cache[key] = compiled
        return compiled

    def match(self, prompt: str) -> SkillMatch | None:
        """Return the first skill that matches `prompt`, or `None`.

        Matching order (deterministic, sorted by skill name):
        1. **Slash command** — `/<skill_name>` short-circuits to that skill
           (case-insensitive). This is the hermes v0.1 / v0.2 contract.
        2. **Regex triggers** — first regex in any skill's `triggers.regex`
           that matches wins.
        3. **Keyword triggers** — case-insensitive substring match against
           the lowercased prompt. If multiple skills match on keywords,
           the first by skill name wins (deterministic but arbitrary;
           v0.3+ can add a proper ranking).

        Skills with no triggers at all never auto-match — they're
        available via `/<name>` only.
        """
        if not prompt or not prompt.strip():
            return None

        prompt_stripped = prompt.strip()

        # 1. Slash command: /<skill_name>
        if prompt_stripped.startswith("/"):
            name = prompt_stripped[1:].split()[0].strip().lower()
            if name:
                try:
                    skill = load_skill(name)
                except SkillNotFoundError:
                    pass
                else:
                    return SkillMatch(skill=skill, trigger_kind="name", trigger_text=name)

        # 2 + 3. Walk skills in sorted-by-name order for determinism.
        for skill in list_skills():
            # 2. Regex
            for pattern in skill.triggers.regex:
                compiled = self._get_compiled(skill, pattern)
                if compiled.search(prompt):
                    return SkillMatch(
                        skill=skill, trigger_kind="regex", trigger_text=pattern
                    )
            # 3. Keyword (case-insensitive substring on lowercased prompt)
            prompt_lower = prompt.lower()
            for keyword in skill.triggers.keywords:
                if keyword and keyword in prompt_lower:
                    return SkillMatch(
                        skill=skill, trigger_kind="keyword", trigger_text=keyword
                    )
        return None

    def match_all(self, prompt: str) -> list[SkillMatch]:
        """Return every skill that matches `prompt`, sorted by score desc.

        Used by tests and by the Web UI's "which skills could apply?"
        debug surface. The first item is the same as `match()`.
        """
        if not prompt or not prompt.strip():
            return []

        prompt_stripped = prompt.strip()
        matches: list[SkillMatch] = []

        if prompt_stripped.startswith("/"):
            name = prompt_stripped[1:].split()[0].strip().lower()
            if name:
                try:
                    skill = load_skill(name)
                except SkillNotFoundError:
                    pass
                else:
                    matches.append(
                        SkillMatch(skill=skill, trigger_kind="name", trigger_text=name)
                    )

        for skill in list_skills():
            for pattern in skill.triggers.regex:
                compiled = self._get_compiled(skill, pattern)
                if compiled.search(prompt):
                    matches.append(
                        SkillMatch(skill=skill, trigger_kind="regex", trigger_text=pattern)
                    )
            prompt_lower = prompt.lower()
            for keyword in skill.triggers.keywords:
                if keyword and keyword in prompt_lower:
                    matches.append(
                        SkillMatch(
                            skill=skill, trigger_kind="keyword", trigger_text=keyword
                        )
                    )
        # Stable: name first (the user's explicit pick), then by (score, name)
        # for determinism. We don't have a real score yet — equal scores
        # fall back to name order.
        matches.sort(key=lambda m: (m.trigger_kind != "name", m.skill.name))
        return matches

    # --- per-session activation ---------------------------------------------

    def _activation_path(self, session_id: str) -> Path:
        if not session_id or not session_id.strip():
            raise SkillActivationError("session_id is required")
        # Reject path-traversal-ish input. session_id is a free-form string
        # in v0.1; v0.3+ will move to UUIDs. For now, normalize and bail
        # if it tries to escape.
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", session_id)
        if safe != session_id:
            raise SkillActivationError(
                f"session_id must match [A-Za-z0-9._-] (got {session_id!r})"
            )
        return get_active_skills_dir() / f"{safe}.txt"

    def active_skills(self, session_id: str) -> list[Skill]:
        """Return the skills active for `session_id` (in declared order).

        Missing activation file = empty list (a session is "active for
        all matched skills" by default, not "active for nothing").
        Skills named in the file that no longer exist on disk are
        silently dropped with a warning.
        """
        if not session_id:
            return []
        path = self._activation_path(session_id)
        if not path.is_file():
            return []
        names: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            name = line.strip()
            if not name or name.startswith("#"):
                continue
            names.append(name)
        result: list[Skill] = []
        for name in names:
            try:
                result.append(load_skill(name))
            except SkillNotFoundError as exc:
                _logger.warning(
                    "active_skills: %s in %s — skill not found, dropping", name, path
                )
                # We don't bubble this up: a missing skill shouldn't
                # block the rest of the session.
                _ = exc
        return result

    def activate_for_session(self, skill_name: str, session_id: str) -> Path:
        """Add `skill_name` to the active list for `session_id`. Idempotent."""
        # Validate the skill exists before writing to disk.
        try:
            load_skill(skill_name)
        except SkillNotFoundError as exc:
            raise SkillActivationError(
                f"cannot activate unknown skill: {skill_name!r}"
            ) from exc

        path = self._activation_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._read_activation_lines(path)
        if skill_name in existing:
            return path  # idempotent
        existing.append(skill_name)
        path.write_text(
            "\n".join(existing) + "\n", encoding="utf-8"
        )
        _logger.info("activated skill %r for session %s", skill_name, session_id)
        return path

    def deactivate_for_session(self, skill_name: str, session_id: str) -> Path:
        """Remove `skill_name` from the active list for `session_id`. Idempotent."""
        path = self._activation_path(session_id)
        if not path.is_file():
            return path  # nothing to do
        existing = self._read_activation_lines(path)
        if skill_name not in existing:
            return path  # already not active
        existing = [n for n in existing if n != skill_name]
        if existing:
            path.write_text("\n".join(existing) + "\n", encoding="utf-8")
        else:
            # Empty list → delete the file to avoid leaving stale state.
            path.unlink()
        _logger.info("deactivated skill %r for session %s", skill_name, session_id)
        return path

    @staticmethod
    def _read_activation_lines(path: Path) -> list[str]:
        if not path.is_file():
            return []
        out: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                out.append(stripped)
        return out

    # --- system-prompt block -------------------------------------------------

    def build_available_skills_block(
        self, session_id: str | None = None, *, include_all: bool = False
    ) -> str:
        """Return the `<available_skills>...</available_skills>` markdown.

        `include_all=False` (the default) is the production behavior:
        emit only the skills that are active for `session_id` (or for
        the matched skill on the current turn, if the agent passed a
        temporary list via the `active_skills` parameter). v0.3+ will
        pass that list in directly; v0.2 reads from the activation
        file.

        `include_all=True` is the test/diagnostic surface: emit every
        loaded skill with its full description. Use sparingly —
        bloats the system prompt.
        """
        if include_all:
            skills = list_skills()
        elif session_id:
            skills = self.active_skills(session_id)
        else:
            skills = []

        if not skills:
            return ""

        lines: list[str] = ["<available_skills>"]
        for skill in sorted(skills, key=lambda s: s.name):
            desc = skill.description.strip()
            lines.append(f"- **{skill.name}** — {desc}")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def inject_into_system_prompt(
        self, system_prompt: str, session_id: str | None = None, *, include_all: bool = False
    ) -> str:
        """Append the `<available_skills>` block to `system_prompt` if non-empty.

        Idempotent: if the system prompt already ends with the block,
        we don't add it twice. This is the function the ReAct agent
        calls before each LLM step.
        """
        block = self.build_available_skills_block(session_id, include_all=include_all)
        if not block:
            return system_prompt
        if block in system_prompt:
            return system_prompt
        sep = "" if system_prompt.endswith("\n") else "\n"
        return f"{system_prompt}{sep}\n{block}\n"

    # --- introspection -------------------------------------------------------

    def resolve_tool(self, tool_ref: str) -> str | None:
        """Resolve a `tools:` reference like `file_tools.read_file` to a real tool name.

        Skills reference tools by their canonical "module.tool" path
        (hermes convention). The actual `ToolRegistry` keys them by
        short name. This helper does the resolution so the Web UI's
        "skills panel" can show a tool badge: "uses file_tools.read_file".

        Returns `None` if the tool is not registered. We do NOT raise —
        an unresolved reference is a soft failure that the LLM will
        see as "no such tool" if it tries to call it.
        """
        from hello_agent.tools.registry import registry  # lazy import: avoid cycles

        # The reference can be `module.tool`, `module.submodule.tool`, or
        # just `tool`. The ToolRegistry stores by short name (`read_file`),
        # so we accept both forms and try last-segment first.
        candidates: list[str] = []
        if "." in tool_ref:
            candidates.append(tool_ref.rsplit(".", 1)[-1])
        candidates.append(tool_ref)

        for candidate in candidates:
            try:
                if registry.get(candidate) is not None:
                    return candidate
            except Exception:  # noqa: BLE001 — never let introspection fail
                continue
        return None

    def validate_all(self) -> dict[str, list[str]]:
        """Walk every loaded skill and collect issues. Used by `hello-agent doctor`.

        Returns `{skill_name: [issue, ...]}` — empty dict = all clean.
        Non-fatal: we report and move on (the skill is still loadable
        and the LLM can still use it; the issues are advisory).
        """
        issues: dict[str, list[str]] = {}
        for skill in list_skills():
            skill_issues: list[str] = []
            # 1. Procedure section is the v0.1 hard requirement.
            if not skill.has_procedure_section:
                skill_issues.append("missing '## Procedure' section in body")
            # 2. Description length (Hermes convention: ≤ 60 chars, we accept ≤ 200).
            if len(skill.description) > 200:
                skill_issues.append(
                    f"description is {len(skill.description)} chars (max 200)"
                )
            # 3. Tool references — at least one should resolve.
            if skill.tools:
                resolved_any = any(self.resolve_tool(t) is not None for t in skill.tools)
                if not resolved_any:
                    skill_issues.append(
                        f"none of tools {skill.tools!r} resolve via ToolRegistry"
                    )
            # 4. Invalid regex triggers (the compile would have logged a
            #    warning; we surface it here too).
            for pattern in skill.triggers.regex:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    skill_issues.append(f"invalid regex trigger {pattern!r}: {exc}")
            if skill_issues:
                issues[skill.name] = skill_issues
        return issues


# ----- Module-level singleton + convenience --------------------------------


_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """Return a process-wide `SkillRegistry` (lazy-constructed)."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def reset_registry() -> None:
    """Drop the module-level singleton. Test helper."""
    global _registry
    _registry = None


# ----- Functional API (mirrors loader.py) ----------------------------------


def match_skill(prompt: str) -> SkillMatch | None:
    """`get_registry().match(prompt)`."""
    return get_registry().match(prompt)


def match_skills(prompt: str) -> list[SkillMatch]:
    """`get_registry().match_all(prompt)`."""
    return get_registry().match_all(prompt)


def active_skills_for(session_id: str) -> list[Skill]:
    """`get_registry().active_skills(session_id)`."""
    return get_registry().active_skills(session_id)


def activate_skill(skill_name: str, session_id: str) -> Path:
    """`get_registry().activate_for_session(skill_name, session_id)`."""
    return get_registry().activate_for_session(skill_name, session_id)


def deactivate_skill(skill_name: str, session_id: str) -> Path:
    """`get_registry().deactivate_for_session(skill_name, session_id)`."""
    return get_registry().deactivate_for_session(skill_name, session_id)


def build_available_skills_block(
    session_id: str | None = None, *, include_all: bool = False
) -> str:
    """`get_registry().build_available_skills_block(session_id, include_all)`."""
    return get_registry().build_available_skills_block(session_id, include_all=include_all)


def inject_skills_into_system_prompt(
    system_prompt: str, session_id: str | None = None, *, include_all: bool = False
) -> str:
    """`get_registry().inject_into_system_prompt(...)`."""
    return get_registry().inject_into_system_prompt(
        system_prompt, session_id, include_all=include_all
    )


def resolve_skill_tool(tool_ref: str) -> str | None:
    """`get_registry().resolve_tool(tool_ref)`."""
    return get_registry().resolve_tool(tool_ref)


__all__ = [
    "SkillMatch",
    "RegistryError",
    "SkillActivationError",
    "SkillRegistry",
    "get_registry",
    "reset_registry",
    "match_skill",
    "match_skills",
    "active_skills_for",
    "activate_skill",
    "deactivate_skill",
    "build_available_skills_block",
    "inject_skills_into_system_prompt",
    "resolve_skill_tool",
]
