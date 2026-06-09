"""`hello-agent skills` — list / show / install SKILL.md files.

Subcommands:

- `skills list`   — show every loaded skill (name + description + is_builtin)
- `skills show <name>` — print the full SKILL.md (frontmatter + body)
- `skills install <path>` — copy a SKILL.md into `~/.hello_agent/skills/`
- `skills validate`   — walk every loaded skill and report issues
                      (missing Procedure section, invalid regex, etc.)

The CLI is a thin wrapper over `hello_agent.skills` — the actual work
happens in the loader + registry. Keeping the CLI small means the
same skill operations are usable from the Web UI (Day 8) without
duplicating logic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from hello_agent.core.logging import get_logger
from hello_agent.skills.loader import (
    install_skill,
    list_skills,
    load_skill,
    reload_skills,
)
from hello_agent.skills.models import SkillError, SkillNotFoundError
from hello_agent.skills.registry import get_registry

app = typer.Typer(help="Manage SKILL.md files (built-in + user-installed).")
logger = get_logger(__name__)


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Drop the loader cache and re-scan the filesystem before listing.",
    ),
) -> None:
    """List every loaded skill (name + description + is_builtin)."""
    if reload:
        reload_skills()
    skills = list_skills()
    if json_output:
        typer.echo(json.dumps([s.to_dict() for s in skills], indent=2, ensure_ascii=False))
        return
    if not skills:
        typer.echo("No skills loaded. Use `hello-agent skills install <path>` to add one.")
        return
    typer.echo(f"{len(skills)} skill(s) loaded:")
    for s in skills:
        kind = "builtin" if s.is_builtin else "user"
        typer.echo(f"  - [bold]{s.name}[/bold]  ({kind})")
        typer.echo(f"      {s.description}")
        if s.frontmatter.tags:
            typer.echo(f"      tags: {', '.join(s.frontmatter.tags)}")


@app.command("show")
def show_cmd(
    name: str = typer.Argument(..., help="Skill name (the frontmatter.name field)."),
    json_output: bool = typer.Option(False, "--json", help="Emit frontmatter as JSON."),
    body: bool = typer.Option(
        False, "--body", help="Print only the body, not the full frontmatter block."
    ),
) -> None:
    """Print the full SKILL.md (frontmatter + body)."""
    try:
        skill = load_skill(name)
    except SkillNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if json_output:
        typer.echo(json.dumps(skill.to_dict(), indent=2, ensure_ascii=False))
        return

    typer.echo(f"# {skill.name}")
    typer.echo(f"# {skill.description}")
    typer.echo(f"# path: {skill.path}  (builtin: {skill.is_builtin})")
    typer.echo(f"# version: {skill.frontmatter.version}  category: {skill.frontmatter.category}")
    if not body:
        typer.echo("\n--- frontmatter ---")
        typer.echo(json.dumps(
            {
                "name": skill.name,
                "description": skill.description,
                "version": skill.frontmatter.version,
                "author": skill.frontmatter.author,
                "license": skill.frontmatter.license,
                "platforms": skill.frontmatter.platforms,
                "tags": skill.frontmatter.tags,
                "category": skill.frontmatter.category,
                "related_skills": skill.frontmatter.related_skills,
                "triggers": {
                    "regex": skill.frontmatter.triggers.regex,
                    "keywords": skill.frontmatter.triggers.keywords,
                },
                "tools": skill.frontmatter.tools,
                "inputs": skill.frontmatter.inputs,
                "outputs": skill.frontmatter.outputs,
            },
            indent=2,
            ensure_ascii=False,
        ))
    typer.echo("\n--- body ---")
    typer.echo(skill.body or "(empty)")


@app.command("install")
def install_cmd(
    path: Annotated[
        Path,
        typer.Argument(help="Path to a SKILL.md to install into ~/.hello_agent/skills/."),
    ],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing user-skill with the same name.",
        ),
    ] = False,
) -> None:
    """Copy a SKILL.md into the user skills directory.

    Refuses to overwrite an existing file with the same frontmatter.name
    unless --force is passed. The source is parsed first; broken SKILL.md
    files are rejected before any copy.
    """
    if not path.is_file():
        typer.echo(f"error: not a file: {path}", err=True)
        raise typer.Exit(code=2)
    if force:
        import os
        os.environ["HELLO_AGENT_SKILL_FORCE_INSTALL"] = "1"
    try:
        dest = install_skill(path)
    except SkillError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"installed: {path} -> {dest}")


@app.command("validate")
def validate_cmd() -> None:
    """Walk every loaded skill and report validation issues."""
    issues = get_registry().validate_all()
    if not issues:
        typer.echo(f"All {len(list_skills())} skill(s) are valid.")
        return
    typer.echo(f"{len(issues)} skill(s) have issues:")
    for name, problems in issues.items():
        typer.echo(f"  - [bold]{name}[/bold]:")
        for p in problems:
            typer.echo(f"      * {p}")
    raise typer.Exit(code=1)


@app.command("reload")
def reload_cmd() -> None:
    """Drop the loader cache and re-scan the skills directories."""
    skills = reload_skills()
    typer.echo(f"reloaded: {len(skills)} skill(s) found")


if __name__ == "__main__":
    # Allow `python -m hello_agent.cli.skills ...` for debugging.
    sys.exit(app() or 0)
