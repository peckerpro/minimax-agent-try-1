"""Example 01 — the 10-line quick chat.

Demonstrates the cheapest agent type in `hello_agent.agents`: `SimpleAgent`.
It performs a single LLM call with no tools and no ReAct loop. Use it for
Q&A, classification, summarization — anywhere you don't need the agent to
look anything up or run any tools.

Real usage:

    uv run python examples/01_quick_chat.py "What's 2+2?"

Self-test (no LLM key / network):

    uv run python examples/01_quick_chat.py --self-test

Exit codes:
    0   success
    1   invalid CLI args
    2   LLM call failed (network / missing key)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Ensure repo root is on sys.path so this script runs from anywhere.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _stub_llm_response(prompt: str) -> str:
    """Return a canned assistant message for the offline smoke test."""
    return f"[self-test] SimpleAgent would call the LLM with: {prompt!r}"


def _run_self_test() -> int:
    """Offline smoke — no LLM call, no network, no env vars."""
    from hello_agent.agents.simple import SimpleAgent
    from hello_agent.core.llm import LLMClient
    from hello_agent.core.types import Message, Role

    # We construct an LLMClient that won't actually need a real API key
    # because we monkeypatch `.chat` below. The base URL doesn't matter
    # since we never connect.
    llm = LLMClient(api_key="sk-self-test", base_url="http://localhost/self-test")

    # Patch the underlying OpenAI client's `chat.completions.create` so the
    # agent's call lands in our stub instead of hitting the network.
    canned = _stub_llm_response("hello")
    fake_msg = type("Msg", (), {"content": canned, "finish_reason": "stop", "tool_calls": None})()
    fake_choice = type("FakeChoice", (), {"message": fake_msg, "finish_reason": "stop"})()
    fake_usage = type("U", (), {"total_tokens": 1})()
    fake_response = type("Resp", (), {"choices": [fake_choice], "usage": fake_usage})()
    fake_sync = type(
        "FakeSync",
        (),
        {"chat": type("Chat", (), {"completions": type("C", (), {"create": staticmethod(lambda **kw: fake_response)})()})()},
    )()
    llm._sync = fake_sync

    agent = SimpleAgent(llm=llm, system_prompt="You are a helpful assistant.")
    state = agent.run("hello")
    assert state.messages[-1].role == Role.ASSISTANT
    assert state.messages[-1].content == canned
    print(f"[self-test] OK: SimpleAgent produced {len(state.messages)} messages, last content = {state.messages[-1].content!r}")
    return 0


def _run_live(user_message: str) -> int:
    """Real LLM call — needs HELLO_AGENT_LLM_API_KEY or .env with LLM_API_KEY."""
    from hello_agent.agents.simple import SimpleAgent
    from hello_agent.core.llm import LLMClient

    llm = LLMClient()  # reads from env / .env
    agent = SimpleAgent(llm=llm, system_prompt="You are a helpful assistant.")
    state = agent.run(user_message)
    reply = state.messages[-1].content or ""
    print(reply)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quick chat with SimpleAgent.")
    parser.add_argument("message", nargs="?", default="hello", help="User message (ignored in --self-test)")
    parser.add_argument("--self-test", action="store_true", help="Offline smoke; no LLM call")
    args = parser.parse_args(argv)

    try:
        if args.self_test:
            return _run_self_test()
        return _run_live(args.message)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())