"""Tests for `hello_agent.windows.autostart`.

These tests run on any platform. On Windows they exercise the real
`winreg`; on non-Windows they inject a fake `winreg` module into
`sys.modules` and patch `os.name = 'nt'` so the code under test takes
the Windows branch.

Marked `@pytest.mark.windows` per the spec; the marker is descriptive
not a skip.
"""
from __future__ import annotations

import sys
from typing import Any

import pytest

pytestmark = pytest.mark.windows


# --- Fake winreg --------------------------------------------------------------


class _FakeWinregKey:
    """A minimal stand-in for a winreg key handle."""

    def __init__(self, store: dict[str, tuple[int, str]]) -> None:
        self._store = store
        self._closed = False

    def __enter__(self) -> _FakeWinregKey:
        return self

    def __exit__(self, *exc: Any) -> None:
        self._closed = True

    @property
    def closed(self) -> bool:
        return self._closed


class _FakeWinreg:
    """Minimal winreg stub: holds an in-memory Run-key dict."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 0x0002
    KEY_READ = 0x0009
    REG_SZ = 1

    def __init__(self) -> None:
        # Value name -> (registry type, value)
        self.store: dict[str, tuple[int, str]] = {}
        # Set True to make the next QueryValueEx raise FileNotFoundError.
        self.raise_on_query: bool = False
        # Set True to make the next DeleteValue raise FileNotFoundError.
        self.raise_on_delete: bool = False
        # Set True to make OpenKey raise FileNotFoundError.
        self.raise_on_open: bool = False
        # Optional OSError message for generic errors.
        self.open_error: str | None = None
        self.delete_error: str | None = None
        self.query_error: str | None = None

    # The autostart module calls these top-level functions.
    def OpenKey(  # noqa: N802 — matches winreg API
        self,
        root: Any,
        subkey: str,
        *args: Any,
        **kwargs: Any,
    ) -> _FakeWinregKey:
        if self.raise_on_open:
            err = FileNotFoundError(self.open_error or "fake open failure")
            raise err
        if self.open_error:
            raise OSError(self.open_error)
        return _FakeWinregKey(self.store)

    def SetValueEx(  # noqa: N802
        self,
        key: _FakeWinregKey,
        value_name: str,
        reserved: Any,
        value_type: int,
        value: str,
    ) -> None:
        key._store[value_name] = (value_type, value)

    def QueryValueEx(  # noqa: N802
        self,
        key: _FakeWinregKey,
        value_name: str,
    ) -> tuple[Any, int]:
        if self.raise_on_query:
            raise FileNotFoundError("fake query miss")
        if self.query_error:
            raise OSError(self.query_error)
        if value_name not in key._store:
            raise FileNotFoundError(f"fake winreg: {value_name} not present")
        _, value = key._store[value_name]
        return value, self.REG_SZ

    def DeleteValue(  # noqa: N802
        self,
        key: _FakeWinregKey,
        value_name: str,
    ) -> None:
        if self.raise_on_delete:
            raise FileNotFoundError("fake delete miss")
        if self.delete_error:
            raise OSError(self.delete_error)
        if value_name not in key._store:
            raise FileNotFoundError(f"fake winreg: {value_name} not present")
        del key._store[value_name]


@pytest.fixture()
def fake_winreg(monkeypatch: pytest.MonkeyPatch) -> _FakeWinreg:
    """Inject a fake winreg into sys.modules AND force os.name='nt'."""
    fake = _FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr("hello_agent.windows.autostart.os.name", "nt")
    return fake


@pytest.fixture()
def autostart_module() -> Any:
    from hello_agent.windows import autostart

    return autostart


# --- Tests ------------------------------------------------------------------


def test_enable_writes_registry_entry(autostart_module: Any, fake_winreg: _FakeWinreg) -> None:
    """enable_autostart writes a REG_SZ value under the Run key."""
    ok = autostart_module.enable_autostart(repo_root=r"D:\repo\hello-agent-2")
    assert ok is True
    assert "hello-agent" in fake_winreg.store
    _, cmd = fake_winreg.store["hello-agent"]
    assert cmd.startswith('uv --directory "')
    assert r"D:\repo\hello-agent-2" in cmd
    assert "hello-agent serve --no-tray" in cmd


def test_enable_is_idempotent(autostart_module: Any, fake_winreg: _FakeWinreg) -> None:
    """A second enable just rewrites the same key."""
    autostart_module.enable_autostart(repo_root="A")
    first = fake_winreg.store["hello-agent"][1]
    autostart_module.enable_autostart(repo_root="B")
    second = fake_winreg.store["hello-agent"][1]
    assert first != second
    assert "B" in second


def test_enable_returns_false_on_oserror(autostart_module: Any, fake_winreg: _FakeWinreg) -> None:
    """enable_autostart returns False (does NOT raise) when the registry is unreachable."""
    fake_winreg.open_error = "boom"
    ok = autostart_module.enable_autostart(repo_root="X")
    assert ok is False


def test_disable_removes_entry(autostart_module: Any, fake_winreg: _FakeWinreg) -> None:
    """disable_autostart deletes the value when present."""
    autostart_module.enable_autostart(repo_root="Z")
    assert "hello-agent" in fake_winreg.store
    assert autostart_module.disable_autostart() is True
    assert "hello-agent" not in fake_winreg.store


def test_disable_when_missing_is_idempotent_true(
    autostart_module: Any, fake_winreg: _FakeWinreg
) -> None:
    """disable_autostart returns True when the value is already absent."""
    assert autostart_module.disable_autostart() is True


def test_disable_returns_false_on_oserror(
    autostart_module: Any, fake_winreg: _FakeWinreg
) -> None:
    """disable_autostart returns False when an OSError is raised."""
    # First populate.
    autostart_module.enable_autostart(repo_root="Z")
    # Then break DeleteValue with an OSError.
    fake_winreg.delete_error = "boom"
    ok = autostart_module.disable_autostart()
    assert ok is False


def test_is_autostart_enabled_when_set(
    autostart_module: Any, fake_winreg: _FakeWinreg
) -> None:
    """Returns True after enable, False before."""
    assert autostart_module.is_autostart_enabled() is False
    autostart_module.enable_autostart(repo_root="Q")
    assert autostart_module.is_autostart_enabled() is True


def test_is_autostart_enabled_on_oserror_returns_false(
    autostart_module: Any, fake_winreg: _FakeWinreg
) -> None:
    """Returns False (does NOT raise) on registry errors."""
    fake_winreg.query_error = "boom"
    assert autostart_module.is_autostart_enabled() is False


def test_get_autostart_entry_returns_none_when_missing(
    autostart_module: Any, fake_winreg: _FakeWinreg
) -> None:
    """Returns None when the entry is absent."""
    assert autostart_module.get_autostart_entry() is None


def test_get_autostart_entry_returns_command(
    autostart_module: Any, fake_winreg: _FakeWinreg
) -> None:
    """Returns a populated AutostartEntry when present."""
    autostart_module.enable_autostart(repo_root=r"D:\work\hello-agent-2")
    entry = autostart_module.get_autostart_entry()
    assert entry is not None
    assert entry.name == "hello-agent"
    assert r"D:\work\hello-agent-2" in entry.command


def test_unsupported_on_non_windows(
    autostart_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On non-Windows, every public function raises AutostartUnsupportedError."""
    monkeypatch.setattr(autostart_module.os, "name", "posix")
    # enable
    with pytest.raises(autostart_module.AutostartUnsupportedError):
        autostart_module.enable_autostart()
    # disable
    with pytest.raises(autostart_module.AutostartUnsupportedError):
        autostart_module.disable_autostart()
    # is_enabled
    with pytest.raises(autostart_module.AutostartUnsupportedError):
        autostart_module.is_autostart_enabled()
    # get_entry
    with pytest.raises(autostart_module.AutostartUnsupportedError):
        autostart_module.get_autostart_entry()


def test_build_command_includes_no_tray(autostart_module: Any) -> None:
    """The bootstrap command always disables the tray (logon session)."""
    cmd = autostart_module._build_command(r"C:\repo")
    assert "serve --no-tray" in cmd
    assert cmd.startswith('uv --directory "')
    # The path itself is quoted; the closing quote is followed by ` run ...`.
    assert r'C:\repo" run hello-agent serve --no-tray' in cmd
    assert cmd.endswith("serve --no-tray")