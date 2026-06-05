"""Smoke test for the core/ layer.

Instantiates LLMClient from config.yaml, runs a 1-token probe
(`max_tokens=1`). If `LLM_API_KEY` is not set, exits 0 silently (CI mode).

Run from the worktree root:
    uv run python scripts/smoke_core.py

Exit codes:
  0   probe succeeded (or skipped — no API key)
  1   probe failed with a non-network error
  2   probe failed because of a network/transport error (likely transient)
"""
from __future__ import annotations

import os
import sys
import traceback


def main() -> int:
    # Bootstrap hello_agent so we can read paths/config/env.
    try:
        from hello_agent.core.config import get_env
        from hello_agent.core.llm import LLMClient
        from hello_agent.core.logging import get_logger
        from hello_agent.core.paths import _apply_profile_override, ensure_home
    except Exception as exc:  # noqa: BLE001 — any import error means install is broken
        print(f"[smoke_core] FAIL: cannot import hello_agent.core: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    log = get_logger("smoke_core")
    _apply_profile_override()
    ensure_home()

    env = get_env()
    if not env.llm_api_key:
        print("[smoke_core] SKIP: LLM_API_KEY not set in env / .env (CI mode)")
        return 0

    print(f"[smoke_core] base_url = {env.llm_base_url}")
    print(f"[smoke_core] model    = {env.llm_model}")
    print(f"[smoke_core] timeout  = {env.llm_timeout_seconds}s, max_retries = {env.llm_max_retries}")

    try:
        client = LLMClient()
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke_core] FAIL: cannot construct LLMClient: {exc}", file=sys.stderr)
        return 1

    # 1-token probe. We don't care WHAT the model returns — only that the
    # call goes through without an unhandled exception.
    from hello_agent.core.types import Message, Role

    try:
        resp = client.chat(
            messages=[Message(role=Role.USER, content="ping")],
            max_tokens=1,
        )
    except Exception as exc:  # noqa: BLE001
        # Distinguish transport (transient) from auth/4xx (config issue).
        msg = str(exc).lower()
        if "auth" in msg or "api key" in msg or "401" in msg or "403" in msg:
            print(f"[smoke_core] FAIL (auth): {exc}", file=sys.stderr)
            return 1
        if "connect" in msg or "timeout" in msg or "resolve" in msg:
            print(f"[smoke_core] FAIL (network): {exc}", file=sys.stderr)
            return 2
        print(f"[smoke_core] FAIL (other): {exc}", file=sys.stderr)
        return 1

    # Sanity-check the response shape.
    try:
        choice = resp.choices[0]
        finish = choice.finish_reason
        content = choice.message.content
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke_core] FAIL: malformed response: {exc}", file=sys.stderr)
        return 1

    print(f"[smoke_core] OK: finish_reason={finish!r}, content={content!r}")
    log.bind(category="llm").info("smoke_core probe ok finish_reason={}", finish)
    return 0


if __name__ == "__main__":
    # Optional --workdir arg lets us point at a different repo checkout in CI.
    if len(sys.argv) > 1 and sys.argv[1] == "--workdir" and len(sys.argv) > 2:
        os.chdir(sys.argv[2])
    sys.exit(main())
