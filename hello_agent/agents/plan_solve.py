"""Plan-and-Solve agent.

Two-stage orchestration inspired by the Plan-and-Solve paper (Wang et al., 2023)
and the datawhale `hello-agents` chapter-4 walkthrough:

  Stage 1 — PLANNING
    A single LLM call asks the model to decompose the user task into a
    numbered list of sub-tasks. The response is parsed as a JSON array
    of {step, description} dicts (with several fallback shapes tolerated).

  Stage 2 — EXECUTION
    For each sub-task, we run one ReAct-style sub-iteration: append the
    step description as a USER message, call the LLM, dispatch any tool
    calls, then move on. The final assistant message of each sub-step is
    captured as the `result` of that step and threaded into the next
    sub-task's USER message as context.

The output of the whole run is the assistant's reply at the end of the
last sub-step. If planning fails (LLM returns garbage), we fall back to
running the original user message as a single sub-step.

Implementation note: we inherit from `ReActAgent` to reuse `_dispatch_tool`
and the standard tool/permission/circuit-breaker wiring. The override is
in `run()`, not `step()` — `step()` is called per sub-step with a tailored
state.
"""
from __future__ import annotations

import json
import re
from typing import Any

from hello_agent.agents.react import FINAL_ANSWER_TOOL, ReActAgent
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import AgentState, Message, Role
from hello_agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


# Default planning prompt. The {task} placeholder is filled with the
# user message. The model is asked to return STRICTLY a JSON array — that
# makes downstream parsing reliable.
_PLANNING_PROMPT = (
    "You are a planning assistant. Decompose the following task into a "
    "small, ordered list of sub-tasks. Each sub-task should be a single, "
    "concrete action that an AI agent with file/shell/web tools can execute "
    "in one or two steps.\n\n"
    "Return STRICTLY a JSON array (no prose, no markdown fences) of objects "
    'with this shape: {{"step": 1, "description": "..."}}. Keep the list '
    "between 1 and 8 sub-tasks. Do not include steps the agent cannot do "
    "(e.g. 'wait for human review').\n\n"
    "Task: {task}\n\n"
    "JSON array:"
)


class PlanAndSolveAgent(ReActAgent):
    """Plan first, then execute each sub-task in order.

    Public surface mirrors `ReActAgent` — drop-in replacement when the
    caller wants explicit planning upfront (e.g. multi-file refactors,
    report generation, anything with 3+ sub-actions).
    """

    DEFAULT_PLANNING_PROMPT = _PLANNING_PROMPT

    def __init__(
        self,
        llm: LLMClient,
        tool_registry: ToolRegistry,
        system_prompt: str = (
            "You are a methodical personal assistant. You plan first, then "
            "execute each sub-task in order. Be concise."
        ),
        max_iterations: int = 30,
        max_cost_per_turn_usd: float = 0.50,
        session_id: str | None = None,
        planning_prompt: str | None = None,
    ):
        super().__init__(
            llm=llm,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            max_cost_per_turn_usd=max_cost_per_turn_usd,
            session_id=session_id,
        )
        self.planning_prompt = planning_prompt or self.DEFAULT_PLANNING_PROMPT

    # --- main entrypoint -----------------------------------------------------

    def run(self, user_message: str) -> AgentState:
        """Plan, then run one ReAct sub-iteration per planned step."""
        state = AgentState(
            session_id=self.session_id,
            messages=[
                Message(role=Role.SYSTEM, content=self.system_prompt),
                Message(role=Role.USER, content=user_message),
            ],
            max_iterations=self.max_iterations,
            max_cost_per_turn_usd=self.max_cost_per_turn_usd,
        )

        # --- stage 1: planning ---
        plan = self._plan(user_message)
        logger.debug("Plan-and-Solve: produced {} sub-task(s)", len(plan))
        # Stash the plan on state for downstream consumers / tests.
        state.plan = plan  # type: ignore[attr-defined]

        # --- stage 2: execute each sub-task ---
        sub_states: list[AgentState] = []
        for i, step in enumerate(plan, start=1):
            sub_state = self._build_substate(step, i, state)
            sub_state = self._run_substep(sub_state)
            sub_states.append(sub_state)
            # Capture the result of this step onto the parent state as a
            # USER-style "previous step result" note.
            result_text = self._extract_assistant_text(sub_state)
            state.messages.append(
                Message(
                    role=Role.USER,
                    content=(
                        f"[Sub-task {i}/{len(plan)} result]\n"
                        f"Task: {step.get('description', '')}\n"
                        f"Result: {result_text}"
                    ),
                )
            )
            state.iteration += sub_state.iteration
            if state.iteration >= state.max_iterations:
                logger.warning("Plan-and-Solve: hit max_iterations at step {}/{}", i, len(plan))
                break

        # Annotate the parent state with the per-step details so tests /
        # downstream consumers can inspect what each sub-task did.
        state.sub_states = sub_states  # type: ignore[attr-defined]
        return state

    # --- internals -----------------------------------------------------------

    def _plan(self, user_message: str) -> list[dict[str, Any]]:
        """Run the planning LLM call and parse the result into a step list."""
        prompt = self.planning_prompt.format(task=user_message)
        try:
            response = self.llm.chat(
                messages=[Message(role=Role.USER, content=prompt)],
                tools=None,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Planning call failed: {} — falling back to single step", exc)
            return [{"step": 1, "description": user_message}]

        raw = response.choices[0].message.content or ""
        steps = self._parse_plan(raw)
        if not steps:
            logger.warning("Could not parse plan; using the user message as a single step")
            return [{"step": 1, "description": user_message}]
        return steps

    @staticmethod
    def _parse_plan(raw: str) -> list[dict[str, Any]]:
        """Parse the planning LLM's reply into a list of step dicts.

        Tolerant of: trailing prose, markdown fences, numbering with
        bullets/dashes, and missing "step" key (we synthesize it).
        """
        text = raw.strip()
        if not text:
            return []

        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # Pull out the first JSON-looking array
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        candidate = match.group(0) if match else text

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            # Last-ditch: try a line-by-line bullet parser
            return _parse_bullets(text)

        if not isinstance(data, list):
            return []

        steps: list[dict[str, Any]] = []
        for i, item in enumerate(data, start=1):
            if isinstance(item, str):
                steps.append({"step": i, "description": item})
            elif isinstance(item, dict):
                desc = item.get("description") or item.get("task") or item.get("action") or ""
                if desc:
                    steps.append({"step": i, "description": str(desc)})
        return steps

    def _build_substate(
        self,
        step: dict[str, Any],
        idx: int,
        parent: AgentState,
    ) -> AgentState:
        """Build a fresh AgentState for one sub-step.

        The sub-step inherits the system prompt from the parent and starts
        with a USER message that frames the current step in context.
        """
        description = step.get("description", "")
        user_msg = (
            f"Working on step {idx}: {description}\n\n"
            "Use tools if needed, then either continue with the next tool "
            f"call OR call the `{FINAL_ANSWER_TOOL}` tool with your result "
            "as the `answer` argument."
        )
        return AgentState(
            session_id=parent.session_id,
            messages=[
                Message(role=Role.SYSTEM, content=parent.messages[0].content or self.system_prompt),
                Message(role=Role.USER, content=user_msg),
            ],
            max_iterations=max(2, parent.max_iterations // 4),  # bound sub-iterations
            max_cost_per_turn_usd=parent.max_cost_per_turn_usd,
        )

    def _run_substep(self, state: AgentState) -> AgentState:
        """Run one sub-step to completion (uses ReActAgent's loop logic)."""
        while state.iteration < state.max_iterations:
            if state.interrupted:
                break
            state = self.step(state)
            state.iteration += 1
            if self._is_terminal(state):
                break
        return state

    @staticmethod
    def _extract_assistant_text(state: AgentState) -> str:
        """Walk back through messages and return the last assistant content."""
        for m in reversed(state.messages):
            if m.role == Role.ASSISTANT and m.content:
                return m.content
        return ""


def _parse_bullets(text: str) -> list[dict[str, Any]]:
    """Last-ditch parser for "1. ... \\n 2. ..." style output."""
    steps: list[dict[str, Any]] = []
    pat = re.compile(r"^\s*(?:\d+[\.\)]\s*|[-*]\s+)(.+)$", re.MULTILINE)
    for i, m in enumerate(pat.finditer(text), start=1):
        steps.append({"step": i, "description": m.group(1).strip()})
    return steps
