"""Desktop GUI shell for hello-agent.

A minimal webview wrapper that opens the same React UI served by
`hello-agent serve` in a native OS window. The backend is owned by
a separate process (`hello-agent serve --no-tray`); the desktop
process only hosts the window. This means:

- web and desktop can run concurrently (web in a browser tab, desktop
  in a native window, both pointing at the same backend)
- backend crash doesn't kill the GUI / GUI crash doesn't kill the backend
- the user can use either without thinking about which one is "active"

This module owns:

- `webview.py` — pywebview window management
- `tray.py` — desktop's own pystray (controls the desktop window, NOT
  the backend's lifecycle)
- the `hello-agent desktop` CLI subcommand
"""
from __future__ import annotations
