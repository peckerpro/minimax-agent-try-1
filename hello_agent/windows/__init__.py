"""Windows-specific helpers: tray, autostart, env probe, hotkeys.

Public surface:
    tray.start_tray / tray.stop_tray         — pystray system tray
    autostart.enable_autostart / ...         — HKCU\\...\\Run registry entry
    env.probe_env                            — env probe for `hello-agent doctor`
    shortcuts.register_hotkey / ...          — optional global hotkey (stretch)

The tray and autostart modules are usable on any platform for *import*;
their public functions raise `AutostartUnsupportedError` on non-Windows.
The `env` and `shortcuts` modules are fully cross-platform.
"""
from __future__ import annotations

from hello_agent.windows import autostart, env, shortcuts, tray

__all__ = ["autostart", "env", "shortcuts", "tray"]