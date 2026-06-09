"""Smoke test for the hello_agent.skills layer.

Exercises the public surface of §6.7 (Day 7 — SKILL.md loader + registry + 3
builtins) end-to-end without spinning up the LLM, the agent loop, or any
external service:

  1. `loader.parse_skill_markdown` — frontmatter + body round-trip on a
     minimal hand-rolled SKILL.md string. Verifies required keys, body
     extraction past the `---` fence, and a malformed frontmatter error.
  2. `loader.list_skills` / `load_skill` round-trip — confirms the three
     built-in SKILL.md files (file_organize / daily_review / obsidian_lookup)
     all load, parse, and carry a `## Procedure` section.
  3. `loader.install_skill` — copy a synthesized SKILL.md into the user
     skills dir; assert it appears in the next `list_skills()`; then
     uninstall (delete the user copy) so the smoke stays hermetic.
  4. `registry.SkillRegistry.match` — known trigger phrases map to the
     expected skill name; non-matching prompts return None.
  5. `registry.activate` / `active_skills` / `deactivate` / `inject_into_system_prompt`
     — the per-session activation flow. After activating one skill for a
     synthetic session, the system prompt gains a single `<available_skills>`
     block containing that skill's name; deactivating returns the prompt
     to its prior content.
  6. CLI subcommand surface — `hello-agent skills --help` exits 0; the
     subcommand list includes list / show / install / validate.

Run from the worktree root:
    uv run python scripts/smoke_skills.py

Exit codes:
  0   every section passed
  1   a section reported a hard failure
  2   an unexpected exception escaped
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

# --- section helpers --------------------------------------------------------


class SmokeError(AssertionError):
    """A section reported a hard failure."""


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def _info(msg: str) -> None:
    print(f"  [..] {msg}")


# --- section 1: parser ------------------------------------------------------


# Minimal hand-rolled SKILL.md content. Lives inline so the smoke test does
# not depend on any file on disk.
_MINIMAL_SKILL_MD = (
    "---\n"
    "name: smoke_test_skill\n"
    "description: A throwaway SKILL.md used by scripts/smoke_skills.py.\n"
    "triggers:\n"
    "  keywords:\n"
    "    - smoke\n"
    "    - smoke test\n"
    "tools:\n"
    "  - file_tools.read_file\n"
    "---\n"
    "## Procedure\n"
    "\n"
    "1. Read the user's prompt.\n"
    "2. Smile.\n"
    "3. Done.\n"
)


def smoke_parser() -> None:
    _section("1. loader.parse_skill_markdown round-trip")
    from hello_agent.skills.loader import parse_skill_markdown

    skill = parse_skill_markdown(_MINIMAL_SKILL_MD)
    assert skill.name == "smoke_test_skill", skill.name
    assert "throwaway" in skill.description
    _ok(f"frontmatter parsed: name={skill.name!r}")

    # body must be past the closing '---' and start with '## Procedure'
    assert "## Procedure" in skill.body, "body should contain the Procedure section"
    _ok("body extraction kept the '## Procedure' section")

    # And the trigger keywords survived parsing
    keywords = skill.frontmatter.triggers.keywords
    assert "smoke" in keywords, f"expected 'smoke' in keywords, got {keywords}"
    _ok(f"triggers.keywords round-tripped: {keywords}")

    # Malformed frontmatter (no closing fence) is rejected, not silently accepted.
    try:
        parse_skill_markdown("---\nname: broken\nstill going\n")
    except Exception as exc:  # noqa: BLE001
        _ok(f"malformed frontmatter rejected: {type(exc).__name__}")
    else:
        raise SmokeError("expected parse_skill_markdown to raise on malformed frontmatter")


# --- section 2: builtins ----------------------------------------------------


EXPECTED_BUILTINS = ("file_organize", "daily_review", "obsidian_lookup")


def smoke_builtins() -> None:
    _section("2. loader.list_skills / load_skill — 3 builtins")
    from hello_agent.skills.loader import list_skills, load_skill

    skills = list_skills()
    loaded_names = sorted(s.name for s in skills)
    for name in EXPECTED_BUILTINS:
        assert name in loaded_names, f"missing builtin {name!r}; got {loaded_names}"
    _ok(f"all 3 builtins listed: {loaded_names}")

    # Each builtin has a Procedure section (the minimum-viable content contract).
    for name in EXPECTED_BUILTINS:
        skill = load_skill(name)
        assert "## Procedure" in skill.body, f"{name} missing '## Procedure'"
        _ok(f"{name!r} loads + has '## Procedure' ({len(skill.body)} chars body)")


# --- section 3: install/uninstall -------------------------------------------


def smoke_install(tmp_home: Path) -> None:
    _section("3. loader.install_skill — copy into user dir, then clean up")
    from hello_agent.skills import loader as loader_mod

    # The install path defaults to ~/.hello_agent/skills. We override the
    # user-skills dir to a temp dir so the smoke stays hermetic and does
    # not pollute the real user skills dir.
    src = tmp_home / "smoke_test_skill.md"
    src.write_text(_MINIMAL_SKILL_MD, encoding="utf-8")
    _ok(f"wrote {src}")

    user_dir = tmp_home / "user_skills"
    user_dir.mkdir(parents=True, exist_ok=True)
    # Override the loader's user-skills dir to the temp one for the
    # duration of this section.
    original_getter = loader_mod.get_user_skills_dir
    loader_mod.get_user_skills_dir = lambda: user_dir  # type: ignore[assignment]
    try:
        loader_mod.reset_loader()
        loader_mod.reload_skills()

        dest = loader_mod.install_skill(src)
        assert dest.exists(), f"install_skill did not create {dest}"
        assert dest.name == "smoke_test_skill.md"
        _ok(f"install_skill copied {src.name} -> {dest.name}")

        # The next list_skills() must include the freshly installed skill.
        names = sorted(s.name for s in loader_mod.list_skills())
        assert "smoke_test_skill" in names, f"smoke_test_skill not in {names}"
        _ok(f"list_skills() now includes smoke_test_skill: {names}")

        # Clean up: delete the user copy so the test is hermetic and
        # re-runnable.
        dest.unlink()
        loader_mod.reset_loader()
        loader_mod.reload_skills()
        names_after = sorted(s.name for s in loader_mod.list_skills())
        assert "smoke_test_skill" not in names_after, "user copy should be gone"
        _ok("uninstalled (deleted user copy + reloaded)")
    finally:
        loader_mod.get_user_skills_dir = original_getter  # type: ignore[assignment]
        loader_mod.reset_loader()
        loader_mod.reload_skills()


# --- section 4: trigger matching --------------------------------------------


def smoke_trigger_matching() -> None:
    _section("4. registry.SkillRegistry.match — known triggers")
    from hello_agent.skills.registry import get_registry

    reg = get_registry()

    # Known trigger phrases map to the expected skill
    cases = [
        ("organize my files please", "file_organize"),
        ("end of day review", "daily_review"),
        ("search my obsidian for hello-agent", "obsidian_lookup"),
    ]
    for prompt, expected_name in cases:
        match = reg.match(prompt)
        assert match is not None, f"no match for {prompt!r}"
        assert match.skill.name == expected_name, (
            f"prompt {prompt!r}: expected {expected_name!r}, got {match.skill.name!r}"
        )
        _ok(f"match({prompt!r}) -> {match.skill.name!r}")

    # And an unrelated prompt matches nothing
    none_match = reg.match("xyzzy nothing burger banana phone")
    assert none_match is None, f"unexpected match for nonsense prompt: {none_match!r}"
    _ok("nonsense prompt matches nothing (None)")


# --- section 5: per-session activation + inject -----------------------------


def smoke_activation(tmp_home: Path) -> None:
    _section("5. registry.activate / inject_into_system_prompt")
    from hello_agent.skills.registry import get_registry

    reg = get_registry()

    # Use a per-run unique session id so successive smoke runs cannot
    # leak state into each other. (The active-skills file lives in
    # `~/.hello_agent/skills/active/<session>.txt` and a fixed id would
    # be a footgun.)
    session_id = f"smoke-test-{tmp_home.name}"
    assert reg.active_skills(session_id) == [], (
        f"expected no active skills for fresh session {session_id!r}, "
        f"got {reg.active_skills(session_id)!r}"
    )
    _ok(f"session {session_id!r} starts with no active skills")

    # Activate one skill, then check the injection appears in the prompt.
    reg.activate_for_session("file_organize", session_id)
    active_names = sorted(s.name for s in reg.active_skills(session_id))
    assert active_names == ["file_organize"], f"expected ['file_organize'], got {active_names}"
    _ok("activate_for_session('file_organize') succeeded")

    base_prompt = "You are hello-agent, a helpful assistant."
    injected = reg.inject_into_system_prompt(base_prompt, session_id=session_id)
    assert "<available_skills>" in injected, "no <available_skills> block in injected prompt"
    assert "file_organize" in injected, "injected block should name the active skill"
    assert injected != base_prompt, "injection should mutate the prompt"
    _ok("injected prompt contains <available_skills> block naming 'file_organize'")

    # Idempotency: re-injecting does not double-append
    injected2 = reg.inject_into_system_prompt(injected, session_id=session_id)
    assert injected2 == injected, "second inject() should be a no-op"
    _ok("second inject() is a no-op (idempotent)")

    # Deactivate and confirm the prompt returns to its prior content
    reg.deactivate_for_session("file_organize", session_id)
    assert reg.active_skills(session_id) == [], (
        f"expected no active skills after deactivate, got {reg.active_skills(session_id)!r}"
    )
    restored = reg.inject_into_system_prompt(base_prompt, session_id=session_id)
    assert restored == base_prompt, "no active skills => prompt should be unchanged"
    _ok("deactivate_for_session() removes the block (prompt returns to base)")


# --- section 6: CLI surface -------------------------------------------------


def smoke_cli_surface() -> None:
    _section("6. CLI surface — 'hello-agent skills --help'")
    # Use a sandboxed env so the CLI does not touch the real user dir.
    env = os.environ.copy()
    env.setdefault("HELLO_AGENT_PROFILE", "test")
    env.setdefault("HELLO_AGENT_HOME", str(Path(os.environ.get("TEMP", "/tmp")) / "smoke_skills_home"))

    result = subprocess.run(
        ["uv", "run", "hello-agent", "skills", "--help"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"'hello-agent skills --help' failed:\n  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
    )
    # typer's help output mentions the subcommand names. We don't depend on
    # exact wording, just that all 4 are present.
    for sub in ("list", "show", "install", "validate"):
        assert sub in result.stdout, f"subcommand {sub!r} not in skills --help output"
    _ok("'hello-agent skills --help' lists list/show/install/validate")


# --- driver -----------------------------------------------------------------


def main() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="smoke_skills_") as td:
        tmp_home = Path(td)
        _info(f"tmp home = {tmp_home}")

        sections: list[tuple[str, callable]] = [
            ("smoke_parser", smoke_parser),
            ("smoke_builtins", smoke_builtins),
            ("smoke_install", lambda: smoke_install(tmp_home)),
            ("smoke_trigger_matching", smoke_trigger_matching),
            ("smoke_activation", lambda: smoke_activation(tmp_home)),
            ("smoke_cli_surface", smoke_cli_surface),
        ]

        for name, fn in sections:
            try:
                fn()
            except SmokeError as exc:
                print(f"  [FAIL] {name}: {exc}", file=sys.stderr)
                failures.append(name)
            except Exception as exc:  # noqa: BLE001
                print(f"  [CRASH] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
                traceback.print_exc()
                failures.append(name)

    if failures:
        print(f"\n[smoke_skills] FAIL: {len(failures)} section(s) failed: {failures}", file=sys.stderr)
        return 1
    print("\n[smoke_skills] OK: all 6 sections passed")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--workdir" and len(sys.argv) > 2:
        os.chdir(sys.argv[2])
    sys.exit(main())
