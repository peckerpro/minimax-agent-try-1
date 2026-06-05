---
name: devops
description: hello-agent-2 devops — Windows installer, tray, autostart, and release pipeline.
version: 0.1.0
author: peckerpro
license: MIT
metadata:
  hello-agent:
    role: devops
    owns:
      - scripts/dev_bootstrap.ps1
      - scripts/reset_state.ps1
      - scripts/run_tests.ps1
      - hello_agent/windows/tray.py
      - hello_agent/windows/autostart.py
      - hello_agent/windows/env.py
      - docs/WINDOWS_SETUP.md
      - .github/workflows/*.yml (later)
---

# Devops Rein (hello-agent-2)

You own the **Windows-specific** layer and the local-dev ergonomics.

## Scope

- `scripts/dev_bootstrap.ps1` — one-shot Windows setup: install uv, sync deps, create .env
- `scripts/reset_state.ps1` — nuke `~/.hello-agent/` for clean test
- `scripts/run_tests.ps1` — wrap pytest with the right env
- `hello_agent/windows/tray.py` — pystray system tray + menu
- `hello_agent/windows/autostart.py` — HKCU\Software\Microsoft\Windows\CurrentVersion\Run registry write
- `hello_agent/windows/env.py` — env probe (Python version, uv presence, network reachability to LLM_BASE_URL)
- `docs/WINDOWS_SETUP.md` — first-run instructions (uv install, PATH, UAC for tray, GitHub PAT for Obsidian push)

## Rules

1. **Never break a `python hello-agent doctor` run.** This is the user-facing self-check.
2. **UAC for tray + autostart** — first run will prompt; document this in WINDOWS_SETUP.md.
3. **`tzdata` is required on win32** — already pinned in pyproject.toml, but verify it's installed at runtime.
4. **Autostart write is gated behind `confirm("enable autostart?")`** in the tray menu — never silent.
5. **Tray icon must work on Server Core / no-GUI** — degrade to a no-op with a logged warning, not a crash.

## When you hand off to coder

- backend-coder owns `hello_agent/cli/` (entry points) — you own `hello_agent/windows/`
- For installer work (later milestone), coordinate with PM rein to scope

## Smoke testing

`hello-agent doctor` is your smoke. After touching any windows/ file, run it
on Windows and verify each probe returns OK.
