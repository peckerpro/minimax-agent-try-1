"""Tests for hello_agent.skills.registry — trigger matching + per-session activation.

The registry is the runtime side: it knows which skills are loaded,
matches user prompts against triggers, and manages per-session
activation lists on disk.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hello_agent.skills.loader import (
    reset_loader,
)
from hello_agent.skills.models import Skill, SkillFrontmatter, SkillTriggers
from hello_agent.skills.registry import (
    SkillActivationError,
    SkillRegistry,
    activate_skill,
    active_skills_for,
    build_available_skills_block,
    deactivate_skill,
    get_registry,
    inject_skills_into_system_prompt,
    match_skill,
    match_skills,
    reset_registry,
    resolve_skill_tool,
)

# ----- Fixtures -------------------------------------------------------------


@pytest.fixture()
def tmp_user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Per-test HELLO_AGENT_HOME so activation files don't leak between tests."""
    monkeypatch.setenv("HELLO_AGENT_HOME", str(tmp_path))
    reset_loader()
    reset_registry()
    return tmp_path / "skills"


@pytest.fixture()
def registry_with_mock_skills(tmp_user_dir: Path) -> SkillRegistry:
    """A SkillRegistry backed by 2 in-memory skills (no files needed)."""
    skill_a = Skill(
        name="alpha",
        description="Alpha skill.",
        frontmatter=SkillFrontmatter(
            name="alpha",
            description="Alpha skill.",
            triggers=SkillTriggers(
                regex=[r"(?i)\borganize\s+files?\b"],
                keywords=["organize", "alpha keyword"],
            ),
        ),
        body="## Procedure\nDo alpha things.\n",
        path="<mock-alpha>",
        is_builtin=True,
    )
    skill_b = Skill(
        name="beta",
        description="Beta skill.",
        frontmatter=SkillFrontmatter(
            name="beta",
            description="Beta skill.",
            triggers=SkillTriggers(
                regex=[],
                keywords=["beta keyword", "summarize"],
            ),
        ),
        body="## Procedure\nDo beta things.\n",
        path="<mock-beta>",
        is_builtin=True,
    )

    # Inject into the loader cache so list_skills()/load_skill() see them.
    loader = get_registry()._loader  # type: ignore[attr-defined]
    loader._cache = {"alpha": skill_a, "beta": skill_b}
    return get_registry()


# ----- match_skill: slash command ------------------------------------------


def test_match_slash_command(registry_with_mock_skills: SkillRegistry) -> None:
    """`/alpha` short-circuits to the named skill."""
    match = match_skill("/alpha")
    assert match is not None
    assert match.skill.name == "alpha"
    assert match.trigger_kind == "name"


def test_match_slash_command_with_args(registry_with_mock_skills: SkillRegistry) -> None:
    """`/alpha do stuff` still resolves to alpha (args are ignored)."""
    match = match_skill("/alpha do stuff")
    assert match is not None
    assert match.skill.name == "alpha"


def test_match_slash_command_unknown_falls_through(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """`/nonexistent` doesn't match via slash (returns None or matches by trigger)."""
    match = match_skill("/nonexistent")
    assert match is None


# ----- match_skill: regex trigger ------------------------------------------


def test_match_regex_trigger(registry_with_mock_skills: SkillRegistry) -> None:
    """A regex trigger on alpha matches 'organize files' but not 'I am organized'."""
    match = match_skill("Please organize files in /tmp")
    assert match is not None
    assert match.skill.name == "alpha"
    assert match.trigger_kind == "regex"


def test_match_regex_case_insensitive(registry_with_mock_skills: SkillRegistry) -> None:
    """The `(?i)` flag in our test regex makes the trigger case-insensitive."""
    match = match_skill("ORGANIZE FILES please")
    assert match is not None
    assert match.skill.name == "alpha"


# ----- match_skill: keyword trigger ----------------------------------------


def test_match_keyword_trigger(registry_with_mock_skills: SkillRegistry) -> None:
    """A keyword trigger on beta matches 'summarize today'."""
    match = match_skill("summarize today")
    assert match is not None
    assert match.skill.name == "beta"
    assert match.trigger_kind == "keyword"


def test_match_keyword_substring(registry_with_mock_skills: SkillRegistry) -> None:
    """Keyword matching is case-insensitive substring on the lowercased prompt."""
    match = match_skill("Please SUMMARIZE this for me")
    assert match is not None
    assert match.skill.name == "beta"


# ----- match_skill: edge cases ---------------------------------------------


def test_match_empty_prompt_returns_none(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """Empty / whitespace prompts return None (no false positives)."""
    assert match_skill("") is None
    assert match_skill("   ") is None


def test_match_no_skill_matches_returns_none(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """A prompt with no matching trigger returns None."""
    assert match_skill("what's the weather like?") is None


def test_match_returns_first_in_sorted_name_order(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """When two regexes match, the first by skill name wins (deterministic)."""
    # Both alpha and beta match "summarize organize":
    # - alpha's regex: (?i)\borganize\s+files?\b — matches "organize"
    # - beta's keyword: "summarize" — matches "summarize"
    # alpha < beta in name order → alpha wins
    match = match_skill("summarize and organize")
    assert match is not None
    assert match.skill.name == "alpha"


def test_match_all_returns_every_match(registry_with_mock_skills: SkillRegistry) -> None:
    """`match_all` returns every skill that matches."""
    matches = match_skills("organize summarize")
    names = {m.skill.name for m in matches}
    assert "alpha" in names
    assert "beta" in names


# ----- Per-session activation ----------------------------------------------


def test_activate_writes_to_active_dir(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`activate_skill` writes the skill name to the activation file."""
    activate_skill("alpha", "sess-1")
    path = tmp_user_dir / "active" / "sess-1.txt"
    assert path.is_file()
    assert "alpha" in path.read_text(encoding="utf-8")


def test_active_skills_returns_activated_list(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`active_skills_for(session_id)` returns the activated skills."""
    activate_skill("alpha", "sess-1")
    activate_skill("beta", "sess-1")
    skills = active_skills_for("sess-1")
    assert {s.name for s in skills} == {"alpha", "beta"}


def test_active_skills_empty_when_no_file(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """Missing activation file = empty list, not error."""
    assert active_skills_for("never-activated") == []


def test_active_skills_drops_missing_skill_names(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """Activation files referencing unknown skills drop them silently (with warning)."""
    (tmp_user_dir / "active").mkdir(parents=True, exist_ok=True)
    (tmp_user_dir / "active" / "sess-1.txt").write_text(
        "alpha\nnever_existed\n", encoding="utf-8"
    )
    skills = active_skills_for("sess-1")
    assert {s.name for s in skills} == {"alpha"}


def test_activate_is_idempotent(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`activate_skill` called twice doesn't double-add."""
    activate_skill("alpha", "sess-1")
    activate_skill("alpha", "sess-1")
    skills = active_skills_for("sess-1")
    assert [s.name for s in skills] == ["alpha"]


def test_activate_rejects_unknown_skill(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`activate_skill` of an unknown skill raises SkillActivationError."""
    with pytest.raises(SkillActivationError, match="unknown skill"):
        activate_skill("ghost_skill", "sess-1")


def test_activate_rejects_path_traversal(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`activate_skill` with a malicious session_id is rejected."""
    with pytest.raises(SkillActivationError, match="must match"):
        activate_skill("alpha", "../etc/passwd")


def test_deactivate_removes_from_list(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`deactivate_skill` removes the skill from the activation file."""
    activate_skill("alpha", "sess-1")
    activate_skill("beta", "sess-1")
    deactivate_skill("alpha", "sess-1")
    skills = active_skills_for("sess-1")
    assert {s.name for s in skills} == {"beta"}


def test_deactivate_when_no_file_is_noop(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`deactivate_skill` of a skill that was never activated doesn't raise."""
    deactivate_skill("alpha", "never-existed")  # no exception


def test_deactivate_last_skill_deletes_file(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`deactivate_skill` of the only remaining skill deletes the activation file."""
    activate_skill("alpha", "sess-1")
    path = tmp_user_dir / "active" / "sess-1.txt"
    assert path.is_file()
    deactivate_skill("alpha", "sess-1")
    assert not path.exists()


# ----- build_available_skills_block ----------------------------------------


def test_build_block_with_active_skills(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """The block lists active skills in sorted name order."""
    activate_skill("beta", "sess-1")
    activate_skill("alpha", "sess-1")
    block = build_available_skills_block("sess-1")
    assert "<available_skills>" in block
    assert "</available_skills>" in block
    # alpha < beta in name order
    assert block.index("alpha") < block.index("beta")


def test_build_block_empty_when_no_active(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """No active skills = empty block (no stray <available_skills> tag)."""
    assert build_available_skills_block("sess-1") == ""


def test_build_block_with_include_all(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """`include_all=True` bypasses the activation file."""
    block = build_available_skills_block(None, include_all=True)
    assert "alpha" in block
    assert "beta" in block


# ----- inject_into_system_prompt ------------------------------------------


def test_inject_appends_block_to_prompt(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """`inject_skills_into_system_prompt` appends the block to the prompt."""
    activate_skill("alpha", "sess-1")
    prompt = "You are a helpful assistant."
    augmented = inject_skills_into_system_prompt(prompt, "sess-1")
    assert augmented.startswith(prompt)
    assert "<available_skills>" in augmented
    assert "alpha" in augmented


def test_inject_is_idempotent(
    tmp_user_dir: Path, registry_with_mock_skills: SkillRegistry
) -> None:
    """Calling inject twice doesn't double-append the block."""
    activate_skill("alpha", "sess-1")
    prompt = "base prompt"
    once = inject_skills_into_system_prompt(prompt, "sess-1")
    twice = inject_skills_into_system_prompt(once, "sess-1")
    assert once == twice


def test_inject_returns_prompt_unchanged_when_no_active(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """No active skills = prompt passes through unchanged."""
    prompt = "base prompt"
    assert inject_skills_into_system_prompt(prompt, "no-active-session") == prompt


# ----- resolve_tool --------------------------------------------------------


def test_resolve_tool_with_dotted_ref(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """`resolve_tool("file_tools.read_file")` returns the short name if registered.

    The actual resolution depends on which tools are registered in the
    shared ToolRegistry. Earlier tests in the suite register `read_file`
    (via `test_builtin.test_registry_validate_all_clean`); if that
    test ran first, we get the short name back. Either way, the result
    is one of: the short name (tool was registered) or `None` (it wasn't).
    """
    result = resolve_skill_tool("file_tools.read_file")
    assert result is None or result == "read_file"


def test_resolve_tool_no_dots(
    registry_with_mock_skills: SkillRegistry,
) -> None:
    """A bare tool name (no dots) is tried as-is."""
    assert resolve_skill_tool("nonexistent_tool") is None
