"""Example 02 — ReAct agent + file_tools.read_file round-trip.

The `ReActAgent` is the default agent type in `hello_agent.agents`. It
loops: call LLM, dispatch any tool_calls, append tool results, repeat
until the LLM emits a final assistant reply. This example wires it up
with the builtin `read_file` tool from `hello_agent.tools.builtin.file_tools`.

Real usage:

    uv run python examples/02_react_with_tools.py

Self-test (no LLM / network):

    uv run python examples/02_react_with_tools.py --self-test

In self-test mode we stub the LLM client so the agent emits a single
`read_file` tool_call against a temp file we create, then emits the
`final_answer` tool to wrap things up. We then assert the agent loop
terminated cleanly with the expected final message.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _run_self_test() -> int:
    """Offline smoke — stub LLM, exercise ReAct loop on a real temp file."""
    from hello_agent.agents.react import FINAL_ANSWER_TOOL, ReActAgent
    from hello_agent.core.llm import LLMClient
    from hello_agent.core.types import Message, Role, ToolCall
    from hello_agent.tools.registry import ToolRegistry

    # 1. Create a temp file the read_file tool will operate on.
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "note.md"
        sample.write_text("hello-agent-2 self-test payload\n", encoding="utf-8")
        sample_path = str(sample)

        # 2. Build a registry with the builtin file_tools enabled.
        registry = ToolRegistry(auto_discover=True)

        # 3. Stub the LLM with two canned responses:
        #    - First call: emit `read_file` tool_call
        #    - Second call: emit `final_answer` tool_call (terminates loop)
        llm = LLMClient(api_key="sk-self-test", base_url="http://localhost/self-test")

        # Fake openai-style response objects.
        def _make_tool_response(name: str, arguments: dict, call_id: str) -> object:
            tc = type(
                "TC",
                (),
                {"id": call_id, "function": type("Fn", (), {"name": name, "arguments": json.dumps(arguments)})()},
            )
            msg = type(
                "Msg",
                (),
                {"content": None, "finish_reason": "tool_calls", "tool_calls": [tc]},
            )()
            choice = type("Choice", (), {"message": msg, "finish_reason": "tool_calls"})()
            usage = type("U", (), {"total_tokens": 1})()
            return type("Resp", (), {"choices": [choice], "usage": usage})()

        def _make_final_response(answer: str) -> object:
            return _make_tool_response(
                FINAL_ANSWER_TOOL,
                {"answer": answer},
                call_id="call_final",
            )

        responses = iter(
            [
                _make_tool_response(
                    "read_file",
                    {"path": sample_path},
                    call_id="call_read",
                ),
                _make_final_response("[self-test] read_file complete"),
            ]
        )

        def _fake_create(**_kw: object) -> object:
            return next(responses)

        llm._sync = type(
            "FakeSync",
            (),
            {"chat": type("Chat", (), {"completions": type("C", (), {"create": staticmethod(_fake_create)})()})()},
        )()

        # 4. Drive the ReAct loop.
        agent = ReActAgent(
            llm=llm,
            tool_registry=registry,
            system_prompt="You are a file-reading demo.",
            max_iterations=5,
        )
        state = agent.run("Read the file at the provided path and summarize it.")

        # 5. Assertions.
        assistant_msgs = [m for m in state.messages if m.role == Role.ASSISTANT]
        tool_msgs = [m for m in state.messages if m.role == Role.TOOL]
        assert tool_msgs, "expected at least one TOOL message (the read_file dispatch)"
        assert tool_msgs[0].tool_name == "read_file"
        assert "hello-agent-2 self-test payload" in tool_msgs[0].content
        assert state.messages[-1].role == Role.ASSISTANT
        assert state.messages[-1].content == "[self-test] read_file complete"
        print(
            f"[self-test] OK: ReAct loop ran {state.iteration} iterations, "
            f"dispatched {len(tool_msgs)} tool(s), final reply = "
            f"{state.messages[-1].content!r}"
        )
        return 0


def _run_live() -> int:
    """Real ReAct loop — needs an LLM key. Reads README.md and asks for a 1-sentence summary."""
    from hello_agent.agents.react import ReActAgent
    from hello_agent.core.llm import LLMClient
    from hello_agent.tools.registry import ToolRegistry

    llm = LLMClient()
    registry = ToolRegistry(auto_discover=True)
    agent = ReActAgent(
        llm=llm,
        tool_registry=registry,
        system_prompt=(
            "You can read files with `read_file`. When the user asks about a file, "
            "use the tool, then call `final_answer` with a concise summary."
        ),
        max_iterations=8,
    )
    readme = _REPO_ROOT / "README.md"
    state = agent.run(f"Read {readme} and give me a one-sentence summary of this project.")
    print(state.messages[-1].content or "(no final answer)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReAct agent with file_tools.read_file.")
    parser.add_argument("--self-test", action="store_true", help="Offline smoke; no LLM call")
    args = parser.parse_args(argv)
    try:
        return _run_self_test() if args.self_test else _run_live()
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())