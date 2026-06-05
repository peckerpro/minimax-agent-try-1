"""Reflection agent.

Run-then-critique pattern (Shinn et al., 2023 — "Reflexion"):

  1. Execute the user task using a standard ReAct loop.
  2. When the loop terminates, ask the LLM to REVIEW the assistant's
     final reply against the user's original request.
  3. If the reviewer says "looks good" (or returns no actionable critique),
     we accept the result and stop.
  4. Otherwise we feed the critique back as a USER message and re-run
     the ReAct loop. Repeat up to `max_reflection_rounds` (default 2).

The reflection prompt is deliberately strict: the reviewer MUST return
either `{"verdict": "ok"}` or `{"verdict": "revise", "critique": "..."}`.
We tolerate loose variants and fall back to a simple string check.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from hello_agent.agents.react import ReActAgent
from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import AgentState, Message, Role
from hello_agent.tools.registry import ToolRegistry

logger = get_logger(__name__)


_REFLECTION_PROMPT = (
    "You are a strict reviewer. The user asked an AI assistant to perform "
    "the task shown below. The assistant's final reply is also shown below.\n\n"
    "Decide whether the reply fully and correctly answers the task. Be "
    "honest — if there are factual errors, missing steps, or unclear "
    "language, flag them.\n\n"
    'Return STRICTLY a JSON object (no prose, no markdown fences) of one '
    'of these two shapes:\n'
    '  - {{"verdict": "ok"}}\n'
    '  - {{"verdict": "revise", "critique": "<specific, actionable feedback>"}}\n\n'
    "User task: {task}\n\n"
    "Assistant reply: {reply}\n\n"
    "JSON object:"
)


Verdict = Literal["ok", "revise"]


class ReflectionAgent(ReActAgent):
    """ReAct + self-critique loop.

    Each reflection round is one full ReAct run on the user message; the
    reviewer is consulted at the end of the run. If the reviewer wants a
    revision, we start a fresh sub-state seeded with the critique and run
    ReAct again. This keeps each round's tool-call history self-contained.
    """

    DEFAULT_REFLECTION_PROMPT = _REFLECTION_PROMPT

    def __init__(
        self,
        llm: LLMClient,
        tool_registry: ToolRegistry,
        system_prompt: str = (
            "You are a careful personal assistant. You double-check your own "
            "work and improve it before declaring success."
        ),
        max_iterations: int = 30,
        max_cost_per_turn_usd: float = 0.50,
        session_id: str | None = None,
        max_reflection_rounds: int = 2,
        reflection_prompt: str | None = None,
    ):
        super().__init__(
            llm=llm,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            max_cost_per_turn_usd=max_cost_per_turn_usd,
            session_id=session_id,
        )
        if max_reflection_rounds < 1:
            raise ValueError("max_reflection_rounds must be >= 1")
        self.max_reflection_rounds = max_reflection_rounds
        self.reflection_prompt = reflection_prompt or self.DEFAULT_REFLECTION_PROMPT

    # --- public entrypoint ---------------------------------------------------

    def run(self, user_message: str) -> AgentState:
        """Run, reflect, iterate."""
        state = self._fresh_state(user_message)
        rounds: list[dict[str, Any]] = []

        for round_idx in range(1, self.max_reflection_rounds + 1):
            state = self._run_react(user_message, state)
            final_text = self._last_assistant_text(state)
            verdict, critique = self._reflect(user_message, final_text)
            rounds.append({"round": round_idx, "verdict": verdict, "critique": critique})
            logger.debug("Reflection round {}: verdict={}", round_idx, verdict)

            if verdict == "ok":
                break

            if round_idx >= self.max_reflection_rounds:
                # Out of rounds — accept the last result.
                break

            # Seed a new sub-state for the next round with the critique.
            state = self._seed_revision(user_message, final_text, critique)

        # Annotate the final state so callers / tests can see reflection history.
        state.reflection_rounds = rounds  # type: ignore[attr-defined]
        return state

    # --- internals -----------------------------------------------------------

    def _fresh_state(self, user_message: str) -> AgentState:
        return AgentState(
            session_id=self.session_id,
            messages=[
                Message(role=Role.SYSTEM, content=self.system_prompt),
                Message(role=Role.USER, content=user_message),
            ],
            max_iterations=self.max_iterations,
            max_cost_per_turn_usd=self.max_cost_per_turn_usd,
        )

    def _run_react(self, user_message: str, state: AgentState) -> AgentState:
        """Run a single ReAct-style loop to completion (or budget exhaustion)."""
        # Make sure SYSTEM and USER messages are at the front.
        if not state.messages or state.messages[0].role != Role.SYSTEM:
            state.messages.insert(0, Message(role=Role.SYSTEM, content=self.system_prompt))
        if not any(m.role == Role.USER for m in state.messages):
            state.messages.append(Message(role=Role.USER, content=user_message))

        while state.iteration < state.max_iterations:
            if state.interrupted:
                break
            state = self.step(state)
            state.iteration += 1
            if self._is_terminal(state):
                break
        return state

    def _reflect(self, user_message: str, final_text: str) -> tuple[Verdict, str | None]:
        """Ask the LLM to review `final_text` and return (verdict, critique)."""
        if not final_text.strip():
            # Nothing to reflect on — accept and stop.
            return "ok", None

        prompt = self.reflection_prompt.format(task=user_message, reply=final_text)
        try:
            response = self.llm.chat(
                messages=[Message(role=Role.USER, content=prompt)],
                tools=None,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reflection call failed: {} — accepting result", exc)
            return "ok", None

        raw = response.choices[0].message.content or ""
        return self._parse_verdict(raw)

    @staticmethod
    def _parse_verdict(raw: str) -> tuple[Verdict, str | None]:
        """Parse the reviewer's JSON reply into (verdict, critique)."""
        text = raw.strip()
        if not text:
            return "ok", None

        # Strip code fences
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        # Pull out the first JSON-looking object
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        candidate = match.group(0) if match else text

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return _parse_verdict_loose(text)

        if not isinstance(data, dict):
            return _parse_verdict_loose(text)

        verdict = str(data.get("verdict", "")).lower().strip()
        if verdict in ("ok", "good", "pass", "accept", "no_issues"):
            return "ok", None
        if verdict in ("revise", "fix", "retry", "needs_revision", "needs_work", "bad"):
            critique = data.get("critique") or data.get("feedback") or data.get("issue")
            if isinstance(critique, str) and critique.strip():
                return "revise", critique.strip()
            return "revise", text
        return _parse_verdict_loose(text)

    def _seed_revision(
        self,
        user_message: str,
        previous_reply: str,
        critique: str | None,
    ) -> AgentState:
        """Build a fresh state for the next round, seeded with the critique."""
        feedback_note = (
            "\n\n[Reviewer feedback from the previous round]\n"
            f"{critique or 'No specific critique — please try again and be more thorough.'}\n\n"
            f"[Your previous reply]\n{previous_reply}\n"
        )
        return AgentState(
            session_id=self.session_id,
            messages=[
                Message(role=Role.SYSTEM, content=self.system_prompt),
                Message(role=Role.USER, content=user_message + feedback_note),
            ],
            max_iterations=self.max_iterations,
            max_cost_per_turn_usd=self.max_cost_per_turn_usd,
        )

    @staticmethod
    def _last_assistant_text(state: AgentState) -> str:
        for m in reversed(state.messages):
            if m.role == Role.ASSISTANT and m.content:
                return m.content
        return ""


def _parse_verdict_loose(text: str) -> tuple[Verdict, str | None]:
    """Heuristic: scan the reviewer's reply for ok / revise markers."""
    lower = text.lower()
    if "no issues" in lower or "looks good" in lower or "all good" in lower:
        return "ok", None
    if "revise" in lower or "needs" in lower or "should" in lower or "missing" in lower:
        return "revise", text
    # Default to accepting the reply if we can't decide.
    return "ok", None
