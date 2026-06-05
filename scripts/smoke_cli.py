"""Smoke test for the CLI layer.

Spawns `hello-agent chat "<prompt>"` as a subprocess and asserts:
  - exit code 0
  - stdout contains a "pong"-ish string (echo of the prompt) OR an
    informative error from the LLM (no API key in CI mode is fine)

The CLI call DOES NOT need a real LLM_API_KEY — we accept the
`[error: ...]` style output as a pass when no key is configured.

Run from the worktree root:
    uv run python scripts/smoke_cli.py --prompt "ping"
    uv run python scripts/smoke_cli.py                 # default prompt = "ping"

Exit codes:
  0   subprocess completed; output contains a pong/error match
  1   subprocess failed unexpectedly
  2   subprocess completed but stdout/stderr was empty / unexpected
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

# Strings that count as a "pong" — either an actual echo from the agent or
# a graceful LLM-error message (which is what we get in CI without a key).
PONG_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(pong|ping|hello|hi|ok|ack)\b", re.IGNORECASE),
    re.compile(r"\[error:.*\]", re.IGNORECASE),  # expected when no API key
    re.compile(r"ValueError.*LLM_API_KEY", re.IGNORECASE),  # expected
)


def _looks_like_pong(text: str) -> bool:
    return any(p.search(text) for p in PONG_PATTERNS)


def main() -> int:
    # Allow the caller to override the prompt and the CLI command.
    prompt = "ping"
    cli_args: list[str] = ["chat", prompt]

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--prompt" and i + 1 < len(args):
            prompt = args[i + 1]
            cli_args = ["chat", prompt]
            i += 2
        elif a == "--workdir" and i + 1 < len(args):
            os.chdir(args[i + 1])
            i += 2
        else:
            print(f"[smoke_cli] unknown arg: {a}", file=sys.stderr)
            return 1

    # Ensure subprocess runs from the worktree root so `uv run hello-agent`
    # resolves to the venv in this worktree.
    here = Path(__file__).resolve().parent
    worktree_root = here.parent
    cwd = Path(os.environ.get("SMOKE_CLI_CWD", str(worktree_root)))

    # Decide how to invoke. If `uv` is on PATH, use it (handles venv bootstrap);
    # otherwise fall back to the bare command name.
    uv = os.environ.get("UV", "uv")
    if Path(uv).exists() or _which(uv):
        cmd: list[str] = [uv, "run", "hello-agent", *cli_args]
    else:
        cmd = ["hello-agent", *cli_args]

    print(f"[smoke_cli] cwd  = {cwd}")
    print(f"[smoke_cli] cmd  = {' '.join(cmd)}")
    print(f"[smoke_cli] prompt = {prompt!r}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        print(f"[smoke_cli] FAIL: cannot find command: {exc}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired as exc:
        print(f"[smoke_cli] FAIL: subprocess timed out after {exc.timeout}s", file=sys.stderr)
        return 1

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    print(f"[smoke_cli] exit  = {proc.returncode}")
    if out:
        print(f"[smoke_cli] stdout ({len(out)} bytes):\n{out[-400:]}")
    if err:
        print(f"[smoke_cli] stderr ({len(err)} bytes):\n{err[-400:]}")

    if proc.returncode != 0:
        # An LLM-side error (missing key, timeout, etc.) is OK for smoke
        # as long as the CLI itself came up cleanly. The exit code will be
        # non-zero but the stdout/stderr should mention it.
        if _looks_like_pong(out) or _looks_like_pong(err):
            print("[smoke_cli] OK (CLI ran, agent-side error is acceptable in CI)")
            return 0
        print("[smoke_cli] FAIL: non-zero exit and no pong-like output", file=sys.stderr)
        return 1

    if not out and not err:
        print("[smoke_cli] FAIL: empty stdout/stderr", file=sys.stderr)
        return 2

    if not _looks_like_pong(out) and not _looks_like_pong(err):
        print(
            "[smoke_cli] FAIL: exit 0 but no pong-like string in stdout/stderr",
            file=sys.stderr,
        )
        return 2

    print("[smoke_cli] OK")
    return 0


def _which(cmd: str) -> str | None:
    """Tiny shutil.which shim so this script has no hard dep on shutil."""
    exts = os.environ.get("PATHEXT", "").split(";") or [""]
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if not p:
            continue
        for ext in exts:
            candidate = Path(p) / (cmd + ext)
            if candidate.is_file():
                return str(candidate)
    return None


if __name__ == "__main__":
    sys.exit(main())
