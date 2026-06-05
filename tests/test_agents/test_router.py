"""Tests for hello_agent.agents.router.TaskRouter.

Exercises both the LLM-based zero-shot classifier and the rule-based
fallback. The router must never raise on classification failures — it
always returns a valid `RouteDecision`.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from hello_agent.agents.plan_solve import PlanAndSolveAgent
from hello_agent.agents.react import ReActAgent
from hello_agent.agents.reflection import ReflectionAgent
from hello_agent.agents.router import (
    VALID_AGENT_TYPES,
    RouteDecision,
    TaskRouter,
)
from hello_agent.agents.simple import SimpleAgent
from hello_agent.core.types import Role
from hello_agent.tools.registry import ToolRegistry

# --- LLM stub ---------------------------------------------------------------


class _StubChoice:
    def __init__(self, content: str) -> None:
        self.message = MagicMock()
        self.message.content = content
        self.message.tool_calls = None
        self.finish_reason = "stop"


class _StubResponse:
    def __init__(self, content: str, usage: Any = None) -> None:
        self.choices = [_StubChoice(content)]
        self.usage = usage


def _llm_returning(content: str) -> MagicMock:
    llm = MagicMock()
    llm.chat.return_value = _StubResponse(content)
    return llm


# --- LLM-tier tests ---------------------------------------------------------


def test_router_llm_tier_picks_react() -> None:
    """When the LLM replies with a JSON label, the router uses it."""
    llm = _llm_returning('{"label": "react", "reason": "needs tools"}')
    router = TaskRouter(llm=llm)
    decision = router.route("find the file size of foo.exe on my machine")
    assert isinstance(decision, RouteDecision)
    assert decision.agent_type == "react"
    assert decision.source == "llm"
    assert decision.reason == "needs tools"


def test_router_llm_tier_picks_plan_solve() -> None:
    llm = _llm_returning('{"label": "plan_solve", "reason": "multi-step refactor"}')
    decision = TaskRouter(llm=llm).route("step by step, refactor this module")
    assert decision.agent_type == "plan_solve"
    assert decision.source == "llm"


def test_router_llm_tier_picks_reflection() -> None:
    llm = _llm_returning('{"label": "reflection", "reason": "needs review"}')
    decision = TaskRouter(llm=llm).route("draft a cover letter")
    assert decision.agent_type == "reflection"
    assert decision.source == "llm"


def test_router_llm_tier_picks_simple() -> None:
    llm = _llm_returning('{"label": "simple", "reason": "factual"}')
    decision = TaskRouter(llm=llm).route("what is the capital of France?")
    assert decision.agent_type == "simple"
    assert decision.source == "llm"


# --- LLM fallback to rules --------------------------------------------------


def test_router_falls_back_to_rules_when_llm_raises() -> None:
    """If the LLM call raises, the router falls back to the rule tier."""
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("provider unavailable")
    decision = TaskRouter(llm=llm).route("search the web for the latest Python 3.13 features")
    # "search the web" is a tool-y keyword → rules pick `react`.
    assert decision.source == "rule"
    assert decision.agent_type == "react"


def test_router_falls_back_to_rules_when_label_is_garbage() -> None:
    """If the LLM returns a malformed label, the router falls back to the rule tier."""
    llm = _llm_returning('{"label": "weird_label", "reason": "unparseable"}')
    decision = TaskRouter(llm=llm).route("step by step refactor this code")
    # Rules detect "step by step" → plan_solve.
    assert decision.source == "rule"
    assert decision.agent_type == "plan_solve"


def test_router_falls_back_when_llm_returns_empty() -> None:
    llm = _llm_returning("")
    decision = TaskRouter(llm=llm).route("search the file system for a config file")
    # "search the file" → tool-y → react via rules.
    assert decision.source == "rule"
    assert decision.agent_type == "react"


# --- rule-tier tests (LLM always broken) ------------------------------------


@pytest.fixture()
def offline_router() -> TaskRouter:
    """A router whose LLM always raises — forces the rule tier."""
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("no key")
    return TaskRouter(llm=llm)


def test_rules_simple_short_factual(offline_router: TaskRouter) -> None:
    decision = offline_router.route("What is 2 + 2?")
    # Question mark AND short length → react (rules don't pick simple for ?)
    assert decision.agent_type == "react"
    assert decision.source == "rule"


def test_rules_simple_short_statement(offline_router: TaskRouter) -> None:
    decision = offline_router.route("the capital of France is Paris")
    # Short, no tool-y words, no question mark → simple.
    assert decision.agent_type == "simple"
    assert decision.source == "rule"


def test_rules_plan_solve_step_by_step(offline_router: TaskRouter) -> None:
    decision = offline_router.route("step by step, organize my files into folders")
    assert decision.agent_type == "plan_solve"
    assert decision.source == "rule"


def test_rules_plan_solve_first_then(offline_router: TaskRouter) -> None:
    decision = offline_router.route("First list the files, then rename them alphabetically")
    assert decision.agent_type == "plan_solve"
    assert decision.source == "rule"


def test_rules_reflection_review(offline_router: TaskRouter) -> None:
    decision = offline_router.route("proofread this cover letter for typos")
    assert decision.agent_type == "reflection"
    assert decision.source == "rule"


def test_rules_react_with_tool_y_keyword(offline_router: TaskRouter) -> None:
    decision = offline_router.route("search the web for the latest Python 3.13 features")
    assert decision.agent_type == "react"
    assert decision.source == "rule"


def test_rules_react_long_ambiguous(offline_router: TaskRouter) -> None:
    decision = offline_router.route(
        "Tell me a long story about a brave knight and the dragon that lived beneath the castle"
    )
    # Long + tool-less → react (the default fallback).
    assert decision.agent_type == "react"
    assert decision.source == "rule"


# --- bare-label extraction ---------------------------------------------------


def test_router_extracts_bare_label_when_no_json() -> None:
    """If the LLM returns prose with a label keyword, the router still picks it up."""
    llm = _llm_returning("I think this is a plan_solve task because of the multi-step nature.")
    decision = TaskRouter(llm=llm).route("do this and that and the other thing")
    assert decision.agent_type == "plan_solve"
    assert decision.source == "llm"


# --- edge cases -------------------------------------------------------------


def test_router_empty_message_returns_react(offline_router: TaskRouter) -> None:
    decision = offline_router.route("")
    assert decision.agent_type == "react"
    assert decision.source == "rule"


def test_router_whitespace_only_returns_react(offline_router: TaskRouter) -> None:
    decision = offline_router.route("   \n\t  ")
    assert decision.agent_type == "react"
    assert decision.source == "rule"


def test_valid_agent_types_constant_is_complete() -> None:
    """Sanity: VALID_AGENT_TYPES contains all 4 documented types."""
    assert set(VALID_AGENT_TYPES) == {"simple", "react", "plan_solve", "reflection"}


# --- dispatch ---------------------------------------------------------------


def test_router_dispatch_returns_correct_agent_type() -> None:
    """TaskRouter.dispatch() instantiates the right Agent class per label."""
    llm = _llm_returning("ignored")
    reg = ToolRegistry()
    sys_p = "you are a test"

    for label, expected_cls in [
        ("simple", SimpleAgent),
        ("react", ReActAgent),
        ("plan_solve", PlanAndSolveAgent),
        ("reflection", ReflectionAgent),
    ]:
        agent = TaskRouter.dispatch(
            agent_type=label,  # type: ignore[arg-type]
            llm=llm,
            tool_registry=reg,
            system_prompt=sys_p,
        )
        assert isinstance(agent, expected_cls), (
            f"dispatch({label!r}) returned {type(agent).__name__}, expected {expected_cls.__name__}"
        )


def test_router_dispatch_passes_session_id() -> None:
    """session_id flows through dispatch() to the agent."""
    agent = TaskRouter.dispatch(
        agent_type="react",
        llm=_llm_returning("ignored"),
        tool_registry=ToolRegistry(),
        system_prompt="x",
        session_id="router-sess-1",
    )
    assert agent.session_id == "router-sess-1"


def test_router_dispatch_invalid_raises() -> None:
    """An unknown agent_type label is rejected loudly."""
    with pytest.raises(ValueError, match="unknown agent type"):
        TaskRouter.dispatch(  # type: ignore[call-overload]
            agent_type="weird",
            llm=_llm_returning("ignored"),
            tool_registry=ToolRegistry(),
            system_prompt="x",
        )


# --- LLM-call shape ----------------------------------------------------------


def test_router_calls_llm_with_correct_message_shape() -> None:
    """The classifier call uses a single USER message containing the prompt."""
    llm = _llm_returning('{"label": "react", "reason": "x"}')
    router = TaskRouter(llm=llm)
    router.route("search the web for foo")

    assert llm.chat.call_count == 1
    call = llm.chat.call_args
    msgs = call.kwargs.get("messages") or call.args[0]
    assert len(msgs) == 1
    assert msgs[0].role == Role.USER
    # The original user prompt must appear in the classifier message
    # (so the LLM has the context to classify).
    assert "search the web for foo" in msgs[0].content


def test_router_uses_zero_temperature() -> None:
    """The classifier call requests temperature=0.0 for determinism."""
    llm = _llm_returning('{"label": "react", "reason": "x"}')
    TaskRouter(llm=llm).route("hello")
    call = llm.chat.call_args
    assert call.kwargs.get("temperature") == 0.0
