"""`hello-agent tools` 鈥?list / enable / disable / show."""
from __future__ import annotations

import json

import typer

from hello_agent.core.logging import get_logger
from hello_agent.tools.registry import registry

app = typer.Typer(help="List and manage registered tools.")
logger = get_logger(__name__)


@app.command("list")
def list_cmd(
    json_output: bool = typer.Option(False, "--json", help="JSON output."),
    all_tools: bool = typer.Option(False, "--all", help="Include disabled tools."),
) -> None:
    """List registered tools."""
    tools = registry.list_all()
    if not all_tools:
        tools = [t for t in tools if registry.is_enabled(t.name)]
    if json_output:
        typer.echo(
            json.dumps(
                [
                    {
                        "name": t.name,
                        "toolset": t.toolset,
                        "dangerous": t.dangerous,
                        "enabled": registry.is_enabled(t.name),
                        "description": t.schema.description,
                    }
                    for t in tools
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return
    if not tools:
        typer.echo("(no tools registered 鈥?did you forget to import hello_agent.tools.builtin?)")
        return
    for t in tools:
        status = "[green]ON[/green]" if registry.is_enabled(t.name) else "[dim]OFF[/dim]"
        flag = "  [red]D[/red]" if t.dangerous else "   "
        typer.echo(f"  {status}  {flag}  [bold]{t.name}[/bold]  ({t.toolset}) 鈥?{t.schema.description[:80]}")


@app.command("enable")
def enable_cmd(
    name: list[str] = typer.Argument(  # noqa: B008 — typer idiom for variadic args
        None, help="Tool name(s) to enable."
    ),
) -> None:
    if not name:
        typer.echo("usage: hello-agent tools enable <name> [<name> ...]", err=True)
        raise typer.Exit(code=2)
    for n in name:
        try:
            registry.enable([n])
            typer.echo(f"enabled {n}")
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"failed to enable {n}: {exc}", err=True)


@app.command("disable")
def disable_cmd(
    name: list[str] = typer.Argument(  # noqa: B008 — typer idiom for variadic args
        None, help="Tool name(s) to disable."
    ),
) -> None:
    if not name:
        typer.echo("usage: hello-agent tools disable <name> [<name> ...]", err=True)
        raise typer.Exit(code=2)
    for n in name:
        registry.disable([n])
        typer.echo(f"disabled {n}")


@app.command("show")
def show_cmd(name: str = typer.Argument(..., help="Tool name.")) -> None:
    try:
        t = registry.get(name)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"not found: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps({
        "name": t.name,
        "toolset": t.toolset,
        "dangerous": t.dangerous,
        "requires_env": t.requires_env,
        "schema": {
            "description": t.schema.description,
            "parameters": t.schema.parameters,
        },
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
