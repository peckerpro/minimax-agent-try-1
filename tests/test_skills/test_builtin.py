"""Tests for hello_agent.skills.builtin — the 3 bundled SKILL.md files ship and parse.

These tests don't exercise the LLM-facing behavior of the skills (that's
in test_registry.py); they verify the SHIP check: each builtin loads,
has a Procedure section, has valid frontmatter, and references tools
that the agent's tool registry can resolve.
"""
from __future__ import annotations

import pytest

from hello_agent.skills.loader import (
    get_builtin_skills_dir,
    list_skills,
    load_skill,
)
from hello_agent.skills.models import Skill

# ----- Builtin directory layout -------------------------------------------


def test_builtin_directory_exists() -> None:
    """The `hello_agent/skills/builtin/` directory exists."""
    assert get_builtin_skills_dir().is_dir()


def test_three_builtins_ship() -> None:
    """Exactly the 3 spec'd builtins are present."""
    names = {s.name for s in list_skills() if s.is_builtin}
    assert names == {"file_organize", "daily_review", "obsidian_lookup"}


# ----- Per-builtin shape checks -------------------------------------------


@pytest.mark.parametrize(
    "name, expected_description_substr",
    [
        ("file_organize", "Categorize"),
        ("daily_review", "Summarize"),
        ("obsidian_lookup", "Search"),
    ],
)
def test_builtin_loads_and_parses(
    name: str, expected_description_substr: str
) -> None:
    """Each builtin loads as a fully populated Skill."""
    skill: Skill = load_skill(name)
    assert skill.name == name
    assert skill.is_builtin is True
    assert expected_description_substr in skill.description
    # Path points at the builtin dir.
    assert "builtin" in skill.path


@pytest.mark.parametrize("name", ["file_organize", "daily_review", "obsidian_lookup"])
def test_builtin_has_procedure_section(name: str) -> None:
    """Every builtin has a `## Procedure` section in its body."""
    skill = load_skill(name)
    assert skill.has_procedure_section, f"{name} missing ## Procedure"
    # And the procedure isn't trivial.
    assert len(skill.body) > 200


@pytest.mark.parametrize("name", ["file_organize", "daily_review", "obsidian_lookup"])
def test_builtin_has_triggers(name: str) -> None:
    """Every builtin declares at least one trigger (regex or keyword)."""
    skill = load_skill(name)
    assert skill.triggers.regex or skill.triggers.keywords, (
        f"{name} has no triggers"
    )


@pytest.mark.parametrize("name", ["file_organize", "daily_review", "obsidian_lookup"])
def test_builtin_has_tools_list(name: str) -> None:
    """Every builtin references at least one tool (Hermes convention)."""
    skill = load_skill(name)
    assert skill.tools, f"{name} has no tools"


# ----- Specific content spot-checks ---------------------------------------


def test_file_organize_relevant_description() -> None:
    """file_organize is about files (descriptions should be on-topic)."""
    skill = load_skill("file_organize")
    assert "file" in skill.description.lower() or "folder" in skill.description.lower()


def test_daily_review_relevant_description() -> None:
    """daily_review is about reviewing the day."""
    skill = load_skill("daily_review")
    assert "session" in skill.description.lower() or "day" in skill.description.lower()


def test_obsidian_lookup_relevant_description() -> None:
    """obsidian_lookup is about searching the obsidian vault."""
    skill = load_skill("obsidian_lookup")
    assert "obsidian" in skill.description.lower()


# ----- validate_all (registry introspection) ------------------------------


def test_registry_validate_all_clean() -> None:
    """All 3 builtins pass the registry's validate_all() check (no issues).

    Note: `validate_all()` checks that at least one tool reference
    resolves via ToolRegistry. By default the tool registry is empty
    in unit tests, so the tool-resolve check WOULD flag builtins.
    We pre-register a few tools so the resolve check has something
    to find.
    """
    from hello_agent.tools.builtin import file_tools, shell_tool
    from hello_agent.tools.registry import registry
    file_tools.register(registry)
    shell_tool.register(registry)

    from hello_agent.skills.registry import get_registry

    issues = get_registry().validate_all()
    # The 3 builtins should have no issues (Procedure + valid frontmatter + tools).
    for name in ("file_organize", "daily_review", "obsidian_lookup"):
        assert name not in issues, f"{name} has issues: {issues.get(name)}"
