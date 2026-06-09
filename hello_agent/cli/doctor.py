"""`hello-agent doctor` — env self-check.

Runs a series of probes (via `windows.env.probe_env`) and prints a
checklist. Returns nonzero exit code if any CRITICAL check fails.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

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


def _probe_dict() -> dict[str, Any]:
    """Run the env probe; fall back to an empty dict if it fails to import.

    `probe_env` is in `hello_agent.windows.env` and imports cleanly on
    any platform; this wrapper only exists so doctor keeps working when
    the windows package is unavailable for some reason.
    """
    try:
        from hello_agent.windows.env import probe_env

        return probe_env()
    except Exception as exc:  # noqa: BLE001
        logger.warning("probe_env failed: {}", exc)
        return {}


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

    probes = _probe_dict()

    if json_output:
        import json as _json

        typer.echo(_json.dumps(probes, indent=2, default=str))
        return

    typer.echo(f"hello-agent {__version__} doctor")
    typer.echo(f"  home: {display_hello_agent_home()}")
    typer.echo("")

    failures = 0
    for label, status, value, hint in _collect_checks(probes):
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


def _collect_checks(probes: dict[str, Any]) -> list[tuple[str, str, str, str | None]]:
    """Build the checklist from the probe dict + a few legacy inline probes.

    Returns a list of (label, status, value, hint) tuples. Status is one
    of: "ok", "warn", "fail".
    """
    out: list[tuple[str, str, str, str | None]] = []
    out.append(("version", "ok", __version__, None))

    # Python — prefer probe_env result; fall back to inline.
    py_version = probes.get("python_version") or sys.version.split()[0]
    out.append(("python", "ok", str(py_version), None))

    # uv
    uv = probes.get("uv_version")
    if uv:
        out.append(("uv", "ok", f"uv {uv}", None))
    elif shutil.which("uv"):
        out.append(("uv", "ok", "uv (version unknown)", None))
    else:
        out.append(
            ("uv", "warn", "not found", "install with `irm https://astral.sh/uv/install.ps1 | iex`")
        )

    # Platform
    platform_name = probes.get("platform") or sys.platform
    out.append(("platform", "ok", str(platform_name), None))

    # Home
    home = display_hello_agent_home()
    home_path = get_hello_agent_home()
    if home_path.exists():
        out.append(("home dir", "ok", home, None))
    else:
        out.append(
            ("home dir", "warn", f"{home} (not yet created; will be created on first use)", None)
        )

    # .env
    env_path = Path(".env")
    if env_path.exists():
        out.append((".env", "ok", "present", None))
    else:
        out.append((".env", "warn", "missing", "Copy-Item .env.example .env and set LLM_API_KEY"))

    # LLM_API_KEY (prefer probe_env result; fall back to inline pydantic check).
    env = get_env()
    api_key_set = probes.get("llm_api_key_set")
    if api_key_set is None:
        api_key_set = bool(env.llm_api_key and env.llm_api_key != "sk-replace-me")
    if api_key_set:
        masked = env.llm_api_key[:6] + "***" + env.llm_api_key[-2:]
        out.append(("LLM_API_KEY", "ok", masked, None))
    else:
        out.append(
            (
                "LLM_API_KEY",
                "fail",
                "(empty or default)",
                "set in .env or HELLO_AGENT_LLM_API_KEY env var",
            )
        )

    # Network — use probe_env's TCP probe if we have a base url.
    base_url = probes.get("llm_base_url") or env.llm_base_url or ""
    if base_url:
        net = probes.get("network_reachable")
        if net is True:
            out.append(("network", "ok", f"can reach {base_url}", None))
        elif net is False:
            out.append(
                (
                    "network",
                    "warn",
                    f"cannot reach {base_url}",
                    "set LLM_BASE_URL to a reachable provider",
                )
            )
        else:
            out.append(("network", "ok", f"using {base_url} (probe inconclusive)", None))
    else:
        out.append(("network", "warn", "no LLM_BASE_URL configured", None))

    # Web extras
    web = probes.get("web_extras")
    if web is True:
        out.append(("web extras", "ok", "fastapi + uvicorn installed", None))
    elif web is False:
        out.append(
            ("web extras", "warn", "missing", "uv sync --extra web (needed for `hello-agent serve`)")
        )

    # Windows extras (only show on Windows or when installed elsewhere)
    win_extras = probes.get("windows_extras")
    if sys.platform == "win32":
        if win_extras is True:
            out.append(("windows extras", "ok", "pystray + pywin32 installed", None))
        elif win_extras is False:
            out.append(
                (
                    "windows extras",
                    "warn",
                    "missing",
                    "uv sync --extra windows (needed for tray + autostart)",
                )
            )
    elif win_extras is True:
        # Cross-platform install with --extra windows; works on macOS/Linux pystray builds.
        out.append(("windows extras", "ok", "pystray installed (cross-platform)", None))

    # MinerU key (optional)
    if env.mineru_api_key:
        out.append(("MINERU_API_KEY", "ok", "set", None))
    else:
        out.append(
            (
                "MINERU_API_KEY",
                "warn",
                "not set",
                "optional — document parsing falls back to markitdown / pypdf",
            )
        )

    return out


if __name__ == "__main__":
    app()