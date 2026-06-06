"""Background Git sync for the Obsidian vault (ENGINEERING.md §7.3).

Periodically:

  1. `git add -A` any new/modified files in the vault
  2. `git commit -m "memory sync: <ts>"` if there are changes
  3. `git push` to the configured remote (only if `OBSIDIAN_GIT_TOKEN` is set)

Cadence comes from `config.memory.obsidian.{auto_commit_minutes,
auto_push_minutes}`. Setting either to 0 disables that step.

The thread is a daemon — it dies with the process. There is no IPC
between the thread and the main agent loop, so the only way to observe
sync state is via the `force_sync()` method (or by reading the git log
in the vault directory).

If `OBSIDIAN_VAULT_PATH` is empty OR `OBSIDIAN_GIT_TOKEN` is empty, this
class is a *no-op* scaffold — `start()` is a no-op, `force_sync()`
returns `{"committed": False, "pushed": False, "reason": "..."}`.

We never call `start()` from any code path triggered by `hello-agent
chat` or the test suite — only the `serve` command / the long-lived
tray use it. Tests and smoke scripts must NOT auto-start the thread.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any

from hello_agent.core.config import get_config
from hello_agent.core.logging import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _run_git(*args: str, cwd: str, check: bool = True) -> tuple[int, str, str]:
    """Run a git command, returning (returncode, stdout, stderr)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    return proc.returncode, proc.stdout, proc.stderr


class GitSync:
    """Background Git sync of the Obsidian vault.

    Public API:
        start()              — start the background thread (idempotent)
        stop()               — stop the thread (no-op if not started)
        is_running()         — True iff the thread is alive
        force_sync()         — manually trigger a commit + push; returns
                               a dict with `committed`, `pushed`, `reason?`
        is_configured()      — True iff vault path AND token are set
    """

    def __init__(self, vault_path: str | Path | None = None) -> None:
        cfg = get_config()
        self.vault_path: Path | None = self._resolve_vault(vault_path)
        self.repo: str = cfg.memory.obsidian_git_repo
        self.token: str | None = cfg.memory.obsidian_git_token or None
        self.commit_interval: int = int(cfg.memory.obsidian_auto_commit_minutes)
        self.push_interval: int = int(cfg.memory.obsidian_auto_push_minutes)
        # Backing state for the worker thread.
        self._lock = Lock()
        self._last_commit: float = 0.0
        self._last_push: float = 0.0
        self._stop_event = threading.Event()
        self._thread: Thread | None = None

    # --- configuration helpers -------------------------------------------

    def is_configured(self) -> bool:
        """True iff a vault path AND a git token are both set."""
        return self.vault_path is not None and bool(self.token)

    @staticmethod
    def _resolve_vault(override: str | Path | None) -> Path | None:
        if override is not None:
            p = Path(override).expanduser()
            if not p.is_absolute():
                from hello_agent.core.paths import get_hello_agent_home

                p = get_hello_agent_home() / p
            return p.resolve()
        try:
            cfg = get_config()
            vp = cfg.memory.obsidian_vault_path
        except Exception:  # noqa: BLE001
            return None
        if not vp:
            return None
        p = Path(vp).expanduser().resolve()
        return p

    # --- public API -------------------------------------------------------

    def start(self) -> bool:
        """Start the background sync thread. Returns True if it started.

        No-op (returns False) when not configured. Safe to call multiple
        times — only the first call spawns a thread.
        """
        if not self.is_configured():
            logger.bind(category="memory").info(
                "GitSync.start: no-op (vault or token missing)"
            )
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        try:
            self._ensure_repo()
        except Exception as exc:  # noqa: BLE001
            logger.bind(category="memory").warning(
                "GitSync._ensure_repo failed: {}", exc
            )
            return False
        self._stop_event.clear()
        self._thread = Thread(
            target=self._loop,
            daemon=True,
            name="obsidian-git-sync",
        )
        self._thread.start()
        logger.bind(category="memory").info(
            "Obsidian git sync started (commit every {}m, push every {}m)",
            self.commit_interval,
            self.push_interval,
        )
        return True

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the background thread. Waits up to `timeout` seconds."""
        self._stop_event.set()
        t = self._thread
        if t is not None:
            t.join(timeout=timeout)
            if t.is_alive():
                logger.bind(category="memory").warning(
                    "GitSync thread did not stop within {}s", timeout
                )
        self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def force_sync(self) -> dict[str, Any]:
        """Manually trigger commit + push. Returns a status dict.

        Always returns a dict (never raises), so the CLI can print it
        cleanly. Keys:
          - committed: bool
          - pushed: bool
          - reason:   str (only present on no-op)
        """
        if not self.is_configured():
            return {
                "committed": False,
                "pushed": False,
                "reason": "obsidian_vault_path or obsidian_git_token not set",
            }
        try:
            committed = self._try_commit()
        except Exception as exc:  # noqa: BLE001
            return {"committed": False, "pushed": False, "reason": str(exc)}
        pushed = False
        if committed:
            try:
                pushed = self._try_push()
            except Exception as exc:  # noqa: BLE001
                return {"committed": True, "pushed": False, "reason": str(exc)}
        return {"committed": committed, "pushed": pushed}

    # --- internals --------------------------------------------------------

    def _ensure_repo(self) -> None:
        assert self.vault_path is not None
        git_dir = self.vault_path / ".git"
        if not git_dir.exists():
            _run_git("init", cwd=str(self.vault_path))
            if self.repo:
                # Build the remote URL. With token → embed in URL for
                # https basic auth. Without token → plain https.
                if self.token:
                    auth_url = f"https://{self.token}@github.com/{self.repo}.git"
                else:
                    auth_url = f"https://github.com/{self.repo}.git"
                # Tolerate the remote-already-exists case.
                _run_git(
                    "remote",
                    "add",
                    "origin",
                    auth_url,
                    cwd=str(self.vault_path),
                    check=False,
                )
            _run_git("add", "-A", cwd=str(self.vault_path), check=False)
            _run_git(
                "commit",
                "--allow-empty",
                "-m",
                "initial: hello-agent memory vault",
                cwd=str(self.vault_path),
                check=False,
            )

    def _loop(self) -> None:
        """Worker thread body. Sleeps 60s between checks."""
        while not self._stop_event.is_set():
            # Sleep in small chunks so stop() returns quickly.
            for _ in range(60):
                if self._stop_event.is_set():
                    return
                time.sleep(1)
            now = time.time()
            try:
                if (
                    self.commit_interval > 0
                    and now - self._last_commit >= self.commit_interval * 60
                ):
                    self._try_commit()
                if (
                    self.push_interval > 0
                    and self.token
                    and now - self._last_push >= self.push_interval * 60
                ):
                    self._try_push()
            except Exception as exc:  # noqa: BLE001
                logger.bind(category="memory").error("git sync loop error: {}", exc)

    def _try_commit(self) -> bool:
        assert self.vault_path is not None
        with self._lock:
            # Detect dirty working tree.
            rc, out, _ = _run_git(
                "status",
                "--porcelain",
                cwd=str(self.vault_path),
                check=False,
            )
            if rc != 0:
                return False
            if not out.strip():
                return False  # nothing to commit
            _run_git("add", "-A", cwd=str(self.vault_path), check=False)
            msg = f"memory sync: {_now_iso()}"
            _run_git(
                "commit",
                "-m",
                msg,
                cwd=str(self.vault_path),
                check=False,
            )
            self._last_commit = time.time()
            logger.bind(category="memory").info("Committed: {}", msg)
            return True

    def _try_push(self) -> bool:
        assert self.vault_path is not None
        if not self.token or not self.repo:
            return False
        with self._lock:
            # The default branch on a fresh `git init` is `master` on
            # older git and `main` on newer. Try `main` first, fall back
            # to `master` if that 404s.
            for branch in ("main", "master"):
                rc, _, err = _run_git(
                    "push",
                    "-u",
                    "origin",
                    branch,
                    cwd=str(self.vault_path),
                    check=False,
                )
                if rc == 0:
                    self._last_push = time.time()
                    logger.bind(category="memory").info("Pushed to remote (branch={})", branch)
                    return True
                if "src refspec" in err or "could not find" in err.lower():
                    continue  # try next branch name
                # Other errors (auth, network) — log and stop trying.
                logger.bind(category="memory").warning(
                    "git push failed (rc={}): {}", rc, err.strip()
                )
                return False
            return False


# Re-export the `os` import for tests that want to monkeypatch the
# environment. (Defined at module level so it's easy to find.)
__all__ = ["GitSync", "Lock", "os", "subprocess"]
