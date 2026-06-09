"""Tests for `hello_agent.windows.tray`.

These tests run on any platform — they mock `pystray.Icon` so we don't
need a graphical desktop. The actual pystray backend (Windows + Linux)
is exercised manually via `hello-agent serve`.

Marked `@pytest.mark.windows` so the test selection on Linux runners is
explicit, but no skip is applied: the code under test does NOT require
Windows.
"""
from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.windows


@pytest.fixture()
def fake_pystray(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace pystray.Icon / Menu / MenuItem with thread-safe fakes.

    Returns a dict of recorders the tests can inspect:
        icons        list of fake Icon instances created by start_tray
        menu_items   list of (label, callable, kwargs) tuples
        separators   count of Menu.SEPARATOR markers
        default_idx  index of the menu item marked as default
    """
    state: dict[str, Any] = {
        "icons": [],
        "menu_items": [],
        "separators": 0,
        "default_idx": -1,
    }

    class FakeIcon:
        def __init__(self, name: str, image: Any, title: str, menu: Any) -> None:
            self.name = name
            self.image = image
            self.title = title
            self.menu = menu
            self.run_started = threading.Event()
            self.stopped = threading.Event()
            state["icons"].append(self)

        def run(self) -> None:
            self.run_started.set()
            # Block until stopped (mirrors the real pystray blocking loop).
            self.stopped.wait(timeout=2.0)

        def stop(self) -> None:
            self.stopped.set()

    class FakeMenu:
        SEPARATOR = object()

        def __init__(self, *items: Any) -> None:
            self.items = list(items)

    class FakeMenuItem:
        def __init__(
            self,
            text: str,
            action: Any,
            *,
            default: bool = False,
            **kwargs: Any,
        ) -> None:
            self.text = text
            self.action = action
            self.default = default
            self.kwargs = kwargs
            state["menu_items"].append((text, action, kwargs))
            if default:
                state["default_idx"] = len(state["menu_items"]) - 1

    fake_module = MagicMock()
    fake_module.Icon = FakeIcon
    fake_module.Menu = FakeMenu
    fake_module.MenuItem = FakeMenuItem
    monkeypatch.setitem(__import__("sys").modules, "pystray", fake_module)

    return state


@pytest.fixture()
def tray_module() -> Any:
    """Import the tray module freshly."""
    from hello_agent.windows import tray as tray_mod

    return tray_mod


def test_load_icon_image_loads_shipped_png(tray_module: Any) -> None:
    """If assets/tray.png exists, _load_icon_image should return it."""
    if not tray_module.ICON_PATH.is_file():
        pytest.skip(f"tray.png missing at {tray_module.ICON_PATH}")
    img = tray_module._load_icon_image()
    assert img is not None
    assert img.size[0] > 0 and img.size[1] > 0


def test_load_icon_image_falls_back_when_missing(
    tray_module: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """When the PNG is missing, _load_icon_image should generate one."""
    monkeypatch.setattr(tray_module, "ICON_PATH", tmp_path / "does-not-exist.png")
    img = tray_module._load_icon_image()
    assert img is not None
    # Fallback is 64x64 per the spec.
    assert img.size == (64, 64)


def test_start_tray_returns_icon_and_spawns_thread(
    tray_module: Any, fake_pystray: dict[str, Any]
) -> None:
    """start_tray returns an Icon instance and runs it in a daemon thread."""
    icon = tray_module.start_tray(web_port=8648)
    assert icon is not None
    assert len(fake_pystray["icons"]) == 1

    # The run() loop should have started. Give the thread a moment to set the flag.
    deadline = time.time() + 2.0
    while time.time() < deadline and not fake_pystray["icons"][0].run_started.is_set():
        time.sleep(0.02)
    assert fake_pystray["icons"][0].run_started.is_set()


def test_start_tray_builds_expected_menu(
    tray_module: Any, fake_pystray: dict[str, Any]
) -> None:
    """Menu contains: Open Web UI (default), New Chat, separator, Run Doctor, separator, Quit."""
    tray_module.start_tray(web_port=8648)
    labels = [item[0] for item in fake_pystray["menu_items"]]
    assert "Open Web UI" in labels
    assert "New Chat" in labels
    assert "Run Doctor" in labels
    assert "Quit" in labels
    # Default action is the first one (Open Web UI)
    assert fake_pystray["default_idx"] >= 0
    assert fake_pystray["menu_items"][fake_pystray["default_idx"]][0] == "Open Web UI"


def test_open_web_menu_opens_browser(
    tray_module: Any, fake_pystray: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clicking Open Web UI calls webbrowser.open with the configured port."""
    calls: list[str] = []
    monkeypatch.setattr(tray_module.webbrowser, "open", lambda url: calls.append(url) or True)
    tray_module.start_tray(web_port=9001)
    open_web = next(a for lbl, a, _ in fake_pystray["menu_items"] if lbl == "Open Web UI")
    open_web(None, None)
    assert calls == ["http://127.0.0.1:9001"]


def test_new_chat_menu_appends_query(
    tray_module: Any, fake_pystray: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clicking New Chat opens the UI with ?new=1."""
    calls: list[str] = []
    monkeypatch.setattr(tray_module.webbrowser, "open", lambda url: calls.append(url) or True)
    tray_module.start_tray(web_port=8648)
    new_chat = next(a for lbl, a, _ in fake_pystray["menu_items"] if lbl == "New Chat")
    new_chat(None, None)
    assert calls == ["http://127.0.0.1:8648/?new=1"]


def test_quit_menu_invokes_shutdown_callback(
    tray_module: Any, fake_pystray: dict[str, Any]
) -> None:
    """Clicking Quit calls icon.stop() AND the registered shutdown callback."""
    fired: list[int] = []

    def shutdown() -> None:
        fired.append(1)

    icon = tray_module.start_tray(web_port=8648, on_shutdown=shutdown)
    assert icon is not None
    quit_action = next(a for lbl, a, _ in fake_pystray["menu_items"] if lbl == "Quit")
    quit_action(icon, None)
    # icon.stop() and shutdown should both fire.
    assert fired == [1]


def test_quit_without_callback_is_safe(
    tray_module: Any, fake_pystray: dict[str, Any]
) -> None:
    """Clicking Quit without a registered callback must not crash."""
    # Clear any previous registration.
    tray_module.set_shutdown_callback(None)
    icon = tray_module.start_tray(web_port=8648)
    assert icon is not None
    quit_action = next(a for lbl, a, _ in fake_pystray["menu_items"] if lbl == "Quit")
    quit_action(icon, None)  # should NOT raise


def test_stop_tray_with_none_is_noop(tray_module: Any) -> None:
    """stop_tray(None) must be a safe no-op."""
    tray_module.stop_tray(None)  # should NOT raise


def test_stop_tray_calls_icon_stop(
    tray_module: Any, fake_pystray: dict[str, Any]
) -> None:
    """stop_tray(icon) calls icon.stop()."""
    tray_module.start_tray(web_port=8648)
    icon = fake_pystray["icons"][0]
    tray_module.stop_tray(icon)
    assert icon.stopped.is_set()


def test_set_shutdown_callback_replaces(
    tray_module: Any,
) -> None:
    """set_shutdown_callback installs a callable that survives start_tray."""

    tray_module.set_shutdown_callback(lambda: None)
    try:
        assert tray_module._shutdown_callback is not None

        def new_cb() -> None:
            pass

        tray_module.set_shutdown_callback(new_cb)
        assert tray_module._shutdown_callback is new_cb
    finally:
        tray_module.set_shutdown_callback(None)
        assert tray_module._shutdown_callback is None