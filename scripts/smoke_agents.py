"""Smoke test for the hello_agent.agents layer.

Exercises the public surface of §6.3 end-to-end without spinning up the
real LLM:

  1. `SimpleAgent` with a mock LLM that returns a fixed string.
  2. `ReActAgent` with a stubbed `ToolRegistry` containing a fake
     `final_answer` tool. The mock LLM emits one tool_call then a
     `final_answer`. The loop must terminate after exactly 2 iterations.
  3. `TaskRouter` with a mock LLM that returns "react" — assert the
     router dispatches a `ReActAgent` instance.
  4. `PlanAndSolveAgent` planning fall-through: a non-JSON plan reply
     must NOT crash the agent.
  5. `ReflectionAgent` short-circuit: one round of execution, no
     critique from the reviewer.

Run from the worktree root:
    uv run python scripts/smoke_agents.py

Exit codes:
  0   every section passed
  1   a section reported a hard failure
  2   an unexpected exception escaped
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any
from unittest.mock import MagicMock

# --- section helpers --------------------------------------------------------


class SmokeError(AssertionError):
    """A section reported a hard failure."""


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def _ok(msg: str) -> None:
    print(f"  [ok] {msg}")


def _info(msg: str) -> None:
    print(f"  [..] {msg}")


# --- LLM stubs --------------------------------------------------------------


class _StubMessage:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _StubChoice:
    def __init__(self, content: str | None, tool_calls: list | None) -> None:
        self.message = _StubMessage(content=content, tool_calls=tool_calls)
        self.finish_reason = "stop"


class _StubResponse:
    def __init__(self, content: str | None = None, tool_calls: list | None = None) -> None:
        self.choices = [_StubChoice(content=content, tool_calls=tool_calls)]
        self.usage = None


def _stub_tool_call(name: str, args: dict, call_id: str) -> Any:
    f = MagicMock()
    f.name = name
    f.arguments = json.dumps(args)
    t = MagicMock()
    t.id = call_id
    t.function = f
    return t


# --- section 1: SimpleAgent -------------------------------------------------


def smoke_simple_agent() -> None:
    _section("1. SimpleAgent with a fixed mock LLM reply")
    from hello_agent.agents.simple import SimpleAgent

    llm = MagicMock()
    llm.chat.return_value = _StubResponse(content="hello from the mock")

    agent = SimpleAgent(llm=llm, system_prompt="be brief")
    state = agent.run("ping")

    assert state.messages, "state.messages should not be empty"
    last = state.messages[-1]
    assert last.role.value == "assistant", f"expected assistant, got {last.role!r}"
    assert last.content == "hello from the mock"
    _ok(f"SimpleAgent returned {last.content!r} (iter={state.iteration})")
    assert state.iteration == 1
    _ok("SimpleAgent ran exactly 1 iteration (single-shot)")


# --- section 2: ReActAgent + final_answer short-circuit ---------------------


def smoke_react_agent_final_answer() -> None:
    _section("2. ReActAgent with a fake final_answer tool")
    from hello_agent.agents.react import FINAL_ANSWER_TOOL, ReActAgent
    from hello_agent.core.types import Role, ToolDefinition, ToolResult
    from hello_agent.tools.registry import ToolRegistry

    reg = ToolRegistry()
    # final_answer tool — registered so the LLM's tool_call has a target.
    reg.register(
        name=FINAL_ANSWER_TOOL,
        toolset="smoke",
        schema=ToolDefinition(
            name=FINAL_ANSWER_TOOL,
            description="Submit the final answer.",
            parameters={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=str(args.get("answer", "")),
        ),
    )
    # echo tool — for the intermediate step.
    reg.register(
        name="echo",
        toolset="smoke",
        schema=ToolDefinition(
            name="echo",
            description="echoes input",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"echo:{args.get('text', '')}",
        ),
    )
    _ok(f"Registered {FINAL_ANSWER_TOOL!r} and 'echo' in a fresh ToolRegistry")

    # Mock LLM: first call → tool_call(echo), second call → final_answer.
    llm = MagicMock()
    llm.chat.side_effect = [
        _StubResponse(tool_calls=[_stub_tool_call("echo", {"text": "hi"}, "call-echo")]),
        _StubResponse(
            tool_calls=[
                _stub_tool_call(
                    FINAL_ANSWER_TOOL, {"answer": "the answer is 42"}, "call-final"
                )
            ]
        ),
    ]

    agent = ReActAgent(llm=llm, tool_registry=reg, max_iterations=10)
    state = agent.run("ask me anything")

    # The loop must terminate after exactly 2 iterations.
    assert state.iteration == 2, f"expected 2 iterations, got {state.iteration}"
    _ok(f"ReAct loop terminated at {state.iteration} iterations (target=2)")

    # The final assistant message must contain the promoted answer.
    last = state.messages[-1]
    assert last.role == Role.ASSISTANT, f"expected assistant, got {last.role!r}"
    assert last.content == "the answer is 42"
    _ok(f"Final message promoted final_answer text: {last.content!r}")

    # The echo tool WAS dispatched (it's not final_answer), but the
    # final_answer tool was NOT dispatched (short-circuit).
    tool_msgs = [m for m in state.messages if m.role == Role.TOOL]
    tool_names_dispatched = {m.tool_name for m in tool_msgs}
    assert "echo" in tool_names_dispatched
    assert FINAL_ANSWER_TOOL not in tool_names_dispatched
    _ok(f"Tools dispatched: {tool_names_dispatched} (final_answer short-circuited)")


# --- section 3: TaskRouter dispatch -----------------------------------------


def smoke_task_router() -> None:
    _section("3. TaskRouter dispatches the right agent type")
    from hello_agent.agents.react import ReActAgent
    from hello_agent.agents.router import TaskRouter

    # Mock LLM replies with `{"label": "react", ...}`.
    llm = MagicMock()
    llm.chat.return_value = _StubResponse(
        content=json.dumps({"label": "react", "reason": "needs tools"})
    )
    router = TaskRouter(llm=llm)
    decision = router.route("find the file size of foo.exe")
    assert decision.agent_type == "react"
    assert decision.source == "llm"
    _ok(f"Router picked: agent_type={decision.agent_type!r} source={decision.source!r}")

    # Dispatch() must return a ReActAgent instance.
    reg = MagicMock()
    agent = TaskRouter.dispatch(
        agent_type=decision.agent_type,
        llm=llm,
        tool_registry=reg,
        system_prompt="be brief",
    )
    assert isinstance(agent, ReActAgent), f"expected ReActAgent, got {type(agent).__name__}"
    _ok(f"Dispatch returned a {type(agent).__name__} instance")


# --- section 4: PlanAndSolveAgent resilience --------------------------------


def smoke_plan_solve_resilience() -> None:
    _section("4. PlanAndSolveAgent handles a garbage plan reply")
    from hello_agent.agents.plan_solve import PlanAndSolveAgent
    from hello_agent.core.types import ToolDefinition, ToolResult
    from hello_agent.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(
        name="echo",
        toolset="smoke",
        schema=ToolDefinition(
            name="echo",
            description="echoes input",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"echo:{args.get('text', '')}",
        ),
    )

    llm = MagicMock()
    # Plan call returns garbage, sub-step returns a text reply.
    llm.chat.side_effect = [
        _StubResponse(content="not even JSON, just prose"),
        _StubResponse(content="ok"),
    ]
    agent = PlanAndSolveAgent(llm=llm, tool_registry=reg)
    state = agent.run("anything")
    plan = getattr(state, "plan", None)
    assert plan is not None and len(plan) == 1
    _ok(f"Plan fell back to 1 step: {plan[0]!r}")
    assert llm.chat.call_count == 2
    _ok("Agent ran 2 LLM calls (plan + 1 sub-step) and did not crash")


# --- section 5: ReflectionAgent short-circuit -------------------------------


def smoke_reflection_short_circuit() -> None:
    _section("5. ReflectionAgent accepts on first try (verdict=ok)")
    from hello_agent.agents.reflection import ReflectionAgent
    from hello_agent.core.types import ToolDefinition, ToolResult
    from hello_agent.tools.registry import ToolRegistry

    reg = ToolRegistry()
    reg.register(
        name="echo",
        toolset="smoke",
        schema=ToolDefinition(
            name="echo",
            description="echoes input",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        ),
        handler=lambda args, **kw: ToolResult(
            tool_call_id=str(kw.get("tool_call_id", "")),
            content=f"echo:{args.get('text', '')}",
        ),
    )

    llm = MagicMock()
    llm.chat.side_effect = [
        _StubResponse(content="here is the answer"),
        _StubResponse(content=json.dumps({"verdict": "ok"})),
    ]
    agent = ReflectionAgent(llm=llm, tool_registry=reg)
    state = agent.run("what is 2+2?")
    rounds = getattr(state, "reflection_rounds", None)
    assert rounds is not None and len(rounds) == 1
    assert rounds[0]["verdict"] == "ok"
    _ok(f"Reflection finished in 1 round: {rounds[0]!r}")
    assert llm.chat.call_count == 2
    _ok("Agent ran 2 LLM calls (exec + reflect) and did not iterate")


# --- driver -----------------------------------------------------------------


def main() -> int:
    failures: list[str] = []

    sections: list[tuple[str, callable]] = [
        ("smoke_simple_agent", smoke_simple_agent),
        ("smoke_react_agent_final_answer", smoke_react_agent_final_answer),
        ("smoke_task_router", smoke_task_router),
        ("smoke_plan_solve_resilience", smoke_plan_solve_resilience),
        ("smoke_reflection_short_circuit", smoke_reflection_short_circuit),
    ]

    for name, fn in sections:
        try:
            fn()
        except SmokeError as exc:
            print(f"  [FAIL] {name}: {exc}", file=sys.stderr)
            failures.append(name)
        except Exception as exc:  # noqa: BLE001
            print(f"  [CRASH] {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
            failures.append(name)

    if failures:
        print(
            f"\n[smoke_agents] FAIL: {len(failures)} section(s) failed: {failures}",
            file=sys.stderr,
        )
        return 1
    print("\n[smoke_agents] OK: all 5 sections passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
