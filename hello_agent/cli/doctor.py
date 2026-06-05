"""`hello-agent doctor` 鈥?env self-check.

Runs a series of probes and prints a checklist. Returns nonzero exit code
if any CRITICAL check fails.
"""
from __future__ import annotations

import shutil
import socket
import sys
from pathlib import Path

import typer

from hello_agent import __version__
from hello_agent.core.config import get_env
from hello_agent.core.logging import get_logger
from hello_agent.core.paths import display_hello_agent_home, ensure_home, get_hello_agent_home

app = typer.Typer(help="Diagnose your hello-agent install.")
logger = get_logger(__name__)


def _ok(label: str, value: str) -> None:
    typer.echo(f"  [green]OK[/green]  {label}: {value}")


def _warn(label: str, value: str, hint: str) -> None:
    typer.echo(f"  [yellow]WARN[/yellow]  {label}: {value}  ({hint})")


def _fail(label: str, value: str, hint: str) -> None:
    typer.echo(f"  [red]FAIL[/red]  {label}: {value}  ({hint})")


@app.command("run")
def run(
    reset_state: bool = typer.Option(False, "--reset-state", help="Wipe hello-agent home before checks"),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Run the env self-check."""
    if reset_state:
        import shutil as _sh

        home = get_hello_agent_home()
        if home.exists():
            typer.echo(f"Removing {home} ...")
            _sh.rmtree(home)
        ensure_home()

    if json_output:
        import json as _json

        typer.echo(_json.dumps(_collect_checks(), indent=2))
        return

    typer.echo(f"hello-agent {__version__} doctor")
    typer.echo(f"  home: {display_hello_agent_home()}")
    typer.echo("")

    failures = 0
    for label, status, value, hint in _collect_checks():
        if status == "ok":
            _ok(label, value)
        elif status == "warn":
            _warn(label, value, hint or "")
        else:
            _fail(label, value, hint or "")
            failures += 1

    typer.echo("")
    if failures:
        typer.echo(f"{failures} check(s) failed.")
        raise typer.Exit(code=1)
    typer.echo("All critical checks pass.")


def _collect_checks() -> list[tuple[str, str, str, str | None]]:
    out: list[tuple[str, str, str, str | None]] = []
    out.append(("version", "ok", __version__, None))

    # Python
    out.append(("python", "ok", sys.version.split()[0], None))

    # uv
    uv = shutil.which("uv")
    out.append(
        ("uv", "ok" if uv else "warn", uv or "not found", "install with `irm https://astral.sh/uv/install.ps1 | iex`")
    )

    # Home
    home = display_hello_agent_home()
    home_path = get_hello_agent_home()
    if home_path.exists():
        out.append(("home dir", "ok", home, None))
    else:
        out.append(("home dir", "warn", f"{home} (not yet created; will be created on first use)", None))

    # .env
    env_path = Path(".env")
    if env_path.exists():
        out.append((".env", "ok", "present", None))
    else:
        out.append((".env", "warn", "missing", "Copy-Item .env.example .env and set LLM_API_KEY"))

    # LLM_API_KEY
    env = get_env()
    if env.llm_api_key and env.llm_api_key != "sk-replace-me":
        masked = env.llm_api_key[:6] + "***" + env.llm_api_key[-2:]
        out.append(("LLM_API_KEY", "ok", masked, None))
    else:
        out.append(("LLM_API_KEY", "fail", "(empty or default)", "set in .env or HELLO_AGENT_LLM_API_KEY env var"))

    # Network 鈥?quick TCP probe to api.openai.com (only if openai base url)
    if "openai.com" in env.llm_base_url:
        try:
            with socket.create_connection(("api.openai.com", 443), timeout=5):
                out.append(("network", "ok", "can reach api.openai.com:443", None))
        except OSError as exc:
            out.append(("network", "warn", f"cannot reach api.openai.com:443 ({exc})", "set LLM_BASE_URL to a reachable provider"))
    else:
        out.append(("network", "ok", f"using {env.llm_base_url} (not probing)", None))

    # MinerU key (optional)
    if env.mineru_api_key:
        out.append(("MINERU_API_KEY", "ok", "set", None))
    else:
        out.append(("MINERU_API_KEY", "warn", "not set", "optional 鈥?document parsing falls back to markitdown / pypdf"))

    return out


if __name__ == "__main__":
    app()
