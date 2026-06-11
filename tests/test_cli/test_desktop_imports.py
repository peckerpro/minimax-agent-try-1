"""Smoke-import tests for the v0.2.2 desktop integration.

These tests assert that the new modules wired up by the desktop
integration commit can be imported cleanly, and that the relevant
``__all__`` symbols are present. We do NOT actually instantiate the
GUI (pywebview requires a display) or spawn a real backend.
"""
from __future__ import annotations


def test_desktop_package_imports() -> None:
    """``hello_agent.desktop`` package imports without side-effects."""
    import hello_agent.desktop  # noqa: F401


def test_desktop_backend_imports() -> None:
    """``hello_agent.desktop.backend`` exports ``BackendManager`` and ``wait_for_backend``."""
    from hello_agent.desktop import backend

    assert hasattr(backend, "BackendManager")
    assert hasattr(backend, "wait_for_backend")
    assert "BackendManager" in backend.__all__
    assert "wait_for_backend" in backend.__all__


def test_desktop_webview_imports() -> None:
    """``hello_agent.desktop.webview`` exposes the public surface."""
    from hello_agent.desktop import webview

    assert hasattr(webview, "APP_NAME")
    assert hasattr(webview, "is_available")
    assert hasattr(webview, "open_window")
    assert hasattr(webview, "open_window_in_thread")
    # is_available should be a callable returning bool, and tolerate
    # the case where pywebview is not installed in CI.
    result = webview.is_available()
    assert isinstance(result, bool)


def test_desktop_tray_imports() -> None:
    """``hello_agent.desktop.tray`` exposes the tray entry points."""
    from hello_agent.desktop import tray

    assert hasattr(tray, "start_desktop_tray")
    assert hasattr(tray, "stop_tray")


def test_cli_desktop_imports() -> None:
    """``hello_agent.cli.desktop`` is a Typer app with both ``default`` and ``open``."""
    from hello_agent.cli import desktop as cli_desktop

    assert hasattr(cli_desktop, "app")
    assert hasattr(cli_desktop, "desktop_default")
    assert hasattr(cli_desktop, "desktop_open")


def test_cli_start_imports() -> None:
    """``hello_agent.cli.start`` exposes the launcher and mode constants."""
    from hello_agent.cli import start as cli_start

    assert hasattr(cli_start, "app")
    assert hasattr(cli_start, "start_main")
    assert hasattr(cli_start, "VALID_MODES")
    # `auto / web / desktop / chat` are the four promised modes.
    assert set(cli_start.VALID_MODES) == {"auto", "web", "desktop", "chat"}


def test_run_backend_module_imports() -> None:
    """``hello_agent._run_backend`` exposes ``main`` for ``python -m`` invocation."""
    from hello_agent import _run_backend

    assert callable(_run_backend.main)


def test_cli_main_registers_desktop_and_start() -> None:
    """``hello-agent --help`` mentions the new ``desktop`` and ``start`` subcommands."""
    import subprocess
    from pathlib import Path

    worktree_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        ["uv", "run", "hello-agent", "--help"],
        cwd=str(worktree_root),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (
        f"hello-agent --help failed:\n"
        f"  stdout={result.stdout!r}\n  stderr={result.stderr!r}"
    )
    help_text = "".join(ch for ch in result.stdout if ch.isprintable() or ch in "\n\r")
    assert "desktop" in help_text
    assert "start" in help_text
