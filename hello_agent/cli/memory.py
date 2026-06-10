"""`hello-agent memory` 鈥?show / search / export / forget / sync."""
from __future__ import annotations

import json

import typer

from hello_agent.core.logging import get_logger

app = typer.Typer(help="Manage long-term memory (Obsidian + SQLite).")
logger = get_logger(__name__)


@app.command("show")
def show(
    limit: int = typer.Option(20, "--limit", "-n"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show recent memory entries (most recently inserted first)."""
    from hello_agent.memory.long_term import LongTermMemory

    mem = LongTermMemory()
    # list_facts() returns all facts ordered by id ASC; reverse so the most
    # recently inserted rows come first, then apply the requested limit.
    rows = list(reversed(mem.list_facts()))[: max(0, int(limit))]
    if json_output:
        typer.echo(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
        return
    if not rows:
        typer.echo(
            "(no memories yet — use `hello-agent memory export` to add one, "
            "or `hello-agent memory search` to query semantically.)"
        )
        return
    for row in rows:
        value = row.get("value", "")
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str)
        typer.echo(
            f"  #{row.get('id', '?')} "
            f"[{row.get('source', '?')}] "
            f"{row.get('key', '?')}: {value[:100]}"
        )


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query."),
    top_k: int = typer.Option(5, "--top-k", "-k"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Search long-term memory semantically."""
    from hello_agent.memory.long_term import LongTermMemory

    mem = LongTermMemory()
    results = mem.search(query, top_k=top_k)
    if json_output:
        typer.echo(json.dumps(results, indent=2, ensure_ascii=False, default=str))
        return
    if not results:
        typer.echo("(no matches)")
        return
    for row in results:
        typer.echo(f"  [{row.get('score', 0):.3f}] {row.get('name') or row.get('id')}: {row.get('content', '')[:200]}")


@app.command("export")
def export(
    content: str = typer.Argument(..., help="Memory content."),
    id: str = typer.Option(..., "--id", help="Stable memory id (used as filename slug)."),
    title: str | None = typer.Option(None, "--title"),
    kind: str = typer.Option("fact", "--kind"),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags."),
) -> None:
    """Write a memory to the Obsidian vault."""
    from hello_agent.memory.obsidian_sync import ObsidianSync

    sync = ObsidianSync()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    path = sync.export_memory(
        memory_id=id,
        content=content,
        kind=kind,
        title=title,
        tags=tag_list,
    )
    typer.echo(f"wrote {path}")


@app.command("forget")
def forget(
    name: str = typer.Argument(..., help="Memory name/id to delete."),
) -> None:
    """Delete a memory from long-term storage and the vault."""
    from hello_agent.memory.long_term import LongTermMemory
    from hello_agent.memory.obsidian_sync import ObsidianSync

    LongTermMemory().delete(name)
    ObsidianSync().delete_memory(name)
    typer.echo(f"forgot {name}")


@app.command("sync")
def sync(force: bool = typer.Option(False, "--force", help="Force a commit+push right now.")) -> None:
    """Trigger an immediate git sync (commit + push) of the Obsidian vault."""
    from hello_agent.memory.git_sync import GitSync

    g = GitSync()
    if force:
        result = g.force_sync()
        typer.echo(json.dumps(result, indent=2))
    else:
        g.start()
        typer.echo("background git sync started")


if __name__ == "__main__":
    app()
