"""Tests for hello_agent.skills.loader — frontmatter parsing, body extraction, name uniqueness.

The loader is the disk-I/O boundary: it reads SKILL.md files, parses
YAML frontmatter, and resolves builtin-vs-user precedence. These tests
exercise the parsing logic with a mix of inline strings and a
per-test temp skills directory.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hello_agent.skills.loader import (
    SkillLoader,
    get_builtin_skills_dir,
    install_skill,
    list_skills,
    load_skill,
    reload_skills,
    reset_loader,
    skill_fingerprint,
)
from hello_agent.skills.models import (
    SkillNotFoundError,
    SkillParseError,
    parse_skill_markdown,
)

# ----- Fixtures -------------------------------------------------------------


@pytest.fixture()
def tmp_user_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point HELLO_AGENT_HOME at a per-test temp dir, return the user skills dir."""
    monkeypatch.setenv("HELLO_AGENT_HOME", str(tmp_path))
    reset_loader()
    user_dir = tmp_path / "skills"
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def _write_skill(path: Path, *, name: str, body: str = "## Procedure\n", extras: str = "") -> Path:
    """Write a minimal-but-valid SKILL.md. `extras` is appended inside the frontmatter block."""
    # No `textwrap.dedent` here: the body content can have arbitrary
    # indentation (and the heredoc in this function can't have a
    # "common leading whitespace" because body is interpolated). Keep
    # the SKILL.md body at column 0 to satisfy the parser's
    # `must start with --- on line 1` invariant.
    text = (
        "---\n"
        f"name: {name}\n"
        f"description: A test skill ({name}).\n"
        "version: 0.1.0\n"
        f"{extras}\n"
        "---\n"
        "\n"
        f"# {name}\n"
        "\n"
        f"{body}\n"
    )
    path.write_text(text, encoding="utf-8")
    return path


# ----- parse_skill_markdown (unit) -----------------------------------------


def test_parse_skill_markdown_minimal() -> None:
    """A SKILL.md with only the required keys parses cleanly."""
    text = textwrap.dedent(
        """\
        ---
        name: minimal
        description: A bare-bones skill.
        ---

        ## Procedure
        Do the thing.
        """
    )
    skill = parse_skill_markdown(text, path="<inline>")
    assert skill.name == "minimal"
    assert skill.description == "A bare-bones skill."
    # body is everything after the frontmatter
    assert "## Procedure" in skill.body
    assert "Do the thing." in skill.body
    assert skill.path == "<inline>"
    assert skill.has_procedure_section is True


def test_parse_skill_markdown_strips_leading_blank_line() -> None:
    """A blank line after the closing `---` is preserved (it's part of the body)."""
    text = "---\nname: x\ndescription: y\n---\n\nBody here.\n"
    skill = parse_skill_markdown(text, path="<inline>")
    assert "Body here." in skill.body


def test_parse_skill_markdown_requires_frontmatter() -> None:
    """A file without the leading `---` fence raises SkillParseError."""
    with pytest.raises(SkillParseError, match="missing YAML frontmatter"):
        parse_skill_markdown("Just some markdown, no fence.\n", path="bad.md")


def test_parse_skill_markdown_requires_name_and_description() -> None:
    """Frontmatter without `name` or `description` raises SkillParseError."""
    with pytest.raises(SkillParseError, match="missing required key"):
        parse_skill_markdown(
            "---\ndescription: no name here\n---\nbody\n", path="bad.md"
        )
    with pytest.raises(SkillParseError, match="missing required key"):
        parse_skill_markdown(
            "---\nname: no_desc\n---\nbody\n", path="bad.md"
        )


def test_parse_skill_markdown_empty_name_rejected() -> None:
    """An empty name in frontmatter raises."""
    with pytest.raises(SkillParseError, match="frontmatter.name is empty"):
        parse_skill_markdown(
            "---\nname: '   '\ndescription: x\n---\nbody\n", path="bad.md"
        )


def test_parse_skill_markdown_description_too_long() -> None:
    """Descriptions > 200 chars are rejected (Hermes convention is 60; we allow up to 200)."""
    long_desc = "x" * 201
    text = f"---\nname: too_long\ndescription: {long_desc}\n---\nbody\n"
    with pytest.raises(SkillParseError, match="description too long"):
        parse_skill_markdown(text, path="bad.md")


def test_parse_skill_markdown_invalid_yaml() -> None:
    """Malformed YAML in the frontmatter raises SkillParseError."""
    text = "---\nname: [\n  - oops\n  bad indent: ]\n---\nbody\n"
    with pytest.raises(SkillParseError, match="invalid YAML"):
        parse_skill_markdown(text, path="bad.md")


def test_parse_skill_markdown_parses_triggers_and_tools() -> None:
    """Triggers + tools lists are parsed into the SkillFrontmatter dataclass."""
    text = textwrap.dedent(
        """\
        ---
        name: with_triggers
        description: Skill with triggers.
        triggers:
          regex:
            - "(?i)\\\\borganize\\\\s+files\\\\b"
          keywords:
            - organize files
        tools:
          - file_tools.read_file
          - file_tools.write_file
        ---

        ## Procedure
        ...
        """
    )
    skill = parse_skill_markdown(text, path="<inline>")
    assert skill.triggers.regex == [r"(?i)\borganize\s+files\b"]
    assert skill.triggers.keywords == ["organize files"]
    assert skill.tools == ["file_tools.read_file", "file_tools.write_file"]


def test_parse_skill_markdown_non_str_input() -> None:
    """`parse_skill_marktext` rejects non-str input defensively."""
    with pytest.raises(SkillParseError, match="must be str"):
        parse_skill_markdown(12345, path="<inline>")  # type: ignore[arg-type]


# ----- SkillLoader: discovery + cache --------------------------------------


def test_loader_builtin_dir_exists() -> None:
    """The builtin skills directory exists in the package layout."""
    assert get_builtin_skills_dir().is_dir()


def test_loader_lists_three_builtins() -> None:
    """The 3 v0.2 builtin skills are shipped and parseable."""
    skills = list_skills()
    names = {s.name for s in skills}
    assert {"file_organize", "daily_review", "obsidian_lookup"}.issubset(names)
    # All builtins
    builtins = {s.name for s in skills if s.is_builtin}
    assert "file_organize" in builtins
    assert builtins == names  # for the test profile, only builtins load


def test_loader_returns_cached_list_on_second_call() -> None:
    """`list_skills(use_cache=True)` (default) returns the same list across calls."""
    first = list_skills()
    second = list_skills()
    assert first == second


def test_loader_reload_rescans_filesystem(tmp_user_dir: Path) -> None:
    """`reload()` drops the cache and rescans — picks up newly-added files."""
    # The loader always has the 3 builtins, so the user dir is what
    # we're exercising. The builtins are present both before and after.
    pre_reload = {s.name for s in list_skills()}
    _write_skill(tmp_user_dir / "alpha.md", name="alpha")
    # Without reload, the new file isn't in the cache yet (built-ins
    # would still match).
    skills = reload_skills()
    assert "alpha" in {s.name for s in skills}
    # And the previously-loaded skills are still there.
    assert pre_reload.issubset({s.name for s in skills})


def test_load_skill_raises_for_missing() -> None:
    """`load_skill("nonexistent")` raises SkillNotFoundError."""
    with pytest.raises(SkillNotFoundError):
        load_skill("definitely_not_a_real_skill_xyz")


def test_load_skill_returns_parsed_skill() -> None:
    """`load_skill("file_organize")` returns a fully populated Skill."""
    skill = load_skill("file_organize")
    assert skill.name == "file_organize"
    assert skill.is_builtin is True
    assert "## Procedure" in skill.body
    assert "file_tools.read_file" in skill.tools


def test_user_skill_overrides_builtin(tmp_user_dir: Path) -> None:
    """A user skill with the same name as a builtin replaces the builtin."""
    _write_skill(
        tmp_user_dir / "file_organize.md",
        name="file_organize",
        body="## Procedure\nCustom override.\n",
    )
    reload_skills()
    skill = load_skill("file_organize")
    assert "Custom override." in skill.body
    assert skill.is_builtin is False


def test_user_skill_invalid_does_not_break_others(tmp_user_dir: Path) -> None:
    """An unparseable user SKILL.md is logged + skipped; valid ones still load."""
    (tmp_user_dir / "broken.md").write_text("not a real frontmatter\n", encoding="utf-8")
    _write_skill(tmp_user_dir / "good.md", name="good")
    reload_skills()
    names = {s.name for s in list_skills()}
    assert "good" in names
    assert "broken" not in names


def test_two_user_skills_with_same_name_keeps_first(tmp_user_dir: Path) -> None:
    """Two user skills with the same frontmatter.name keep the first (alphabetical)."""
    _write_skill(tmp_user_dir / "a_dup.md", name="dup", body="## Procedure\nfirst\n")
    _write_skill(tmp_user_dir / "b_dup.md", name="dup", body="## Procedure\nsecond\n")
    reload_skills()
    skill = load_skill("dup")
    # alphabetical order: a_dup.md wins
    assert "first" in skill.body


# ----- install_skill --------------------------------------------------------


def test_install_skill_copies_into_user_dir(tmp_user_dir: Path, tmp_path: Path) -> None:
    """`install_skill(src)` copies a valid SKILL.md into the user dir."""
    src = tmp_path / "test_skill.md"
    _write_skill(src, name="test_skill")
    dest = install_skill(src)
    assert dest.is_file()
    assert dest.parent == tmp_user_dir
    # And it's now loadable.
    reload_skills()
    assert load_skill("test_skill").name == "test_skill"


def test_install_skill_rejects_unparseable(tmp_user_dir: Path, tmp_path: Path) -> None:
    """A broken SKILL.md is rejected before any copy happens."""
    src = tmp_path / "broken.md"
    src.write_text("not a real frontmatter\n", encoding="utf-8")
    with pytest.raises(SkillParseError):
        install_skill(src)
    # No file should be created in the user dir.
    assert list(tmp_user_dir.iterdir()) == []


def test_install_skill_refuses_overwrite_without_force(
    tmp_user_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reinstalling a skill with the same name refuses without HELLO_AGENT_SKILL_FORCE_INSTALL=1."""
    monkeypatch.delenv("HELLO_AGENT_SKILL_FORCE_INSTALL", raising=False)
    src = tmp_path / "test_skill.md"
    _write_skill(src, name="test_skill")
    install_skill(src)
    # Second install should fail.
    with pytest.raises(SkillParseError, match="already installed"):
        install_skill(src)


def test_install_skill_with_force_overwrites(
    tmp_user_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HELLO_AGENT_SKILL_FORCE_INSTALL=1 allows overwrite."""
    monkeypatch.setenv("HELLO_AGENT_SKILL_FORCE_INSTALL", "1")
    src = tmp_path / "test_skill.md"
    _write_skill(src, name="test_skill")
    install_skill(src)
    install_skill(src)  # should not raise


def test_install_skill_rejects_non_md(tmp_user_dir: Path, tmp_path: Path) -> None:
    """A non-.md file is rejected with SkillParseError."""
    src = tmp_path / "not_markdown.txt"
    src.write_text("---\nname: x\ndescription: y\n---\nbody\n", encoding="utf-8")
    with pytest.raises(SkillParseError, match="must be .md"):
        install_skill(src)


def test_install_skill_rejects_missing_source(tmp_user_dir: Path, tmp_path: Path) -> None:
    """A nonexistent source path raises SkillNotFoundError."""
    with pytest.raises(SkillNotFoundError, match="does not exist"):
        install_skill(tmp_path / "does_not_exist.md")


# ----- skill_fingerprint ---------------------------------------------------


def test_skill_fingerprint_is_deterministic() -> None:
    """`skill_fingerprint(skill)` is stable across calls."""
    skill = load_skill("file_organize")
    fp1 = skill_fingerprint(skill)
    fp2 = skill_fingerprint(skill)
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex


def test_skill_fingerprint_differs_per_skill() -> None:
    """Different skills get different fingerprints (different bodies)."""
    a = load_skill("file_organize")
    b = load_skill("daily_review")
    assert skill_fingerprint(a) != skill_fingerprint(b)


# ----- SkillLoader instance API --------------------------------------------


def test_skill_loader_can_use_custom_dirs(tmp_path: Path) -> None:
    """A SkillLoader constructed with explicit user/builtin dirs only scans those."""
    user = tmp_path / "user"
    builtin = tmp_path / "builtin"
    user.mkdir()
    builtin.mkdir()
    _write_skill(user / "my_skill.md", name="my_skill")
    _write_skill(builtin / "their_skill.md", name="their_skill")

    loader = SkillLoader(user_dir=user, builtin_dir=builtin)
    skills = loader.list_skills()
    names = {s.name for s in skills}
    assert names == {"my_skill", "their_skill"}
    # The "my_skill" came from user, the other from builtin.
    by_name = {s.name: s for s in skills}
    assert by_name["my_skill"].is_builtin is False
    assert by_name["their_skill"].is_builtin is True
