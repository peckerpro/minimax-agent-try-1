"""Task router — classify a user prompt and dispatch to the right agent type.

Two-tier classification (per ENGINEERING.md §6.3 + the v0.3 hint there):

  Tier 1 — LLM-based zero-shot classifier
    We make a single, cheap LLM call asking the model to pick one of
    {simple, react, plan_solve, reflection} and explain briefly. The
    reply is parsed for the first matching label keyword.

  Tier 2 — Rule-based fallback
    If the LLM call fails (no API key, timeout, parse error), we apply a
    small set of heuristic rules. The rules are intentionally conservative
    — they err on the side of `react` (the default) rather than guessing
    `simple` for an ambiguous prompt.

The router itself does NOT instantiate agents; it only returns a label
and a small `RouteDecision` object. Callers wire the label to the
appropriate agent class (e.g. `SimpleAgent`, `ReActAgent`, …) via
`TaskRouter.dispatch(...)`, which keeps the router itself LLM-agnostic.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from hello_agent.core.llm import LLMClient
from hello_agent.core.logging import get_logger
from hello_agent.core.types import Message, Role

if TYPE_CHECKING:
    pass  # Agent is imported lazily in dispatch() to avoid a circular import.

logger = get_logger(__name__)


AgentType = Literal["simple", "react", "plan_solve", "reflection"]
VALID_AGENT_TYPES: tuple[AgentType, ...] = ("simple", "react", "plan_solve", "reflection")


# Default classification prompt. Tuned to be terse so the call is cheap.
_CLASSIFIER_PROMPT = (
    "You classify user prompts for an AI agent runtime. Pick exactly one "
    "of these labels:\n"
    "  - simple         : a single, factual, no-tools question (e.g. 'what is 2+2?')\n"
    "  - react          : a question that needs tools to answer (search, fetch, "
    "file read, run a command, etc.)\n"
    '  - plan_solve     : a multi-step task that benefits from explicit planning '
    '("step by step", "first X then Y", numbered goals)\n'
    "  - reflection     : a task where the answer should be reviewed/improved "
    "before delivery (writing, code review, refactor with verification)\n\n"
    "User prompt: {prompt}\n\n"
    'Return STRICTLY a JSON object (no prose, no markdown fences): '
    '{{"label": "<one of: simple|react|plan_solve|reflection>", "reason": "<one short sentence>"}}\n\n'
    "JSON object:"
)


@dataclass
class RouteDecision:
    """Result of a routing decision.

    Attributes:
        agent_type: One of `simple` / `react` / `plan_solve` / `reflection`.
        source:     "llm" if the LLM classifier decided, "rule" if the
                    rule-based fallback decided.
        reason:     Short human-readable explanation (LLM "reason" or rule name).
    """

    agent_type: AgentType
    source: Literal["llm", "rule", "explicit"]
    reason: str = ""
    raw: str | None = field(default=None, repr=False)


class TaskRouter:
    """Pick an agent type for a given user prompt.

    Usage:
        router = TaskRouter(llm)
        decision = router.route("what's 2+2?")
        # → RouteDecision(agent_type="simple", source="llm", reason="...")

    The router never raises on classification failures — it always
    returns a valid `RouteDecision` (degrading to `react` if both tiers
    fail to produce a label).
    """

    DEFAULT_CLASSIFIER_PROMPT = _CLASSIFIER_PROMPT
    FALLBACK_LABEL: AgentType = "react"

    def __init__(
        self,
        llm: LLMClient,
        classifier_prompt: str | None = None,
    ) -> None:
        self.llm = llm
        self.classifier_prompt = classifier_prompt or self.DEFAULT_CLASSIFIER_PROMPT

    # --- public API ----------------------------------------------------------

    def route(self, user_message: str) -> RouteDecision:
        """Classify a user message; return a RouteDecision.

        Tries the LLM first, then falls back to rule-based heuristics,
        and finally to `react` (the configured default).
        """
        if not user_message or not user_message.strip():
            return RouteDecision(
                agent_type=self.FALLBACK_LABEL,
                source="rule",
                reason="empty user message; defaulting to react",
            )

        # Tier 1: LLM zero-shot classifier
        decision = self._classify_with_llm(user_message)
        if decision is not None:
            return decision

        # Tier 2: rule-based fallback
        return self._classify_with_rules(user_message)

    @staticmethod
    def dispatch(
        agent_type: AgentType,
        *,
        llm: LLMClient,
        tool_registry,
        system_prompt: str = "You are a helpful personal assistant.",
        max_iterations: int = 30,
        max_cost_per_turn_usd: float = 0.50,
        session_id: str | None = None,
    ) -> object:
        """Instantiate the agent class for `agent_type`.

        Returns the agent instance (subclass of `Agent`). Typed as `object`
        to avoid a circular import; the actual returned type is one of
        `SimpleAgent`, `ReActAgent`, `PlanAndSolveAgent`, `ReflectionAgent`.

        Imports are deferred so callers who only need a label don't pay
        for module imports they don't use.
        """
        from hello_agent.agents.plan_solve import PlanAndSolveAgent
        from hello_agent.agents.react import ReActAgent
        from hello_agent.agents.reflection import ReflectionAgent
        from hello_agent.agents.simple import SimpleAgent

        common = {
            "llm": llm,
            "tool_registry": tool_registry,
            "system_prompt": system_prompt,
            "max_iterations": max_iterations,
            "max_cost_per_turn_usd": max_cost_per_turn_usd,
            "session_id": session_id,
        }
        if agent_type == "simple":
            return SimpleAgent(
                llm=llm,
                system_prompt=system_prompt,
                max_iterations=1,
                max_cost_per_turn_usd=max_cost_per_turn_usd,
                session_id=session_id,
            )
        if agent_type == "react":
            return ReActAgent(**common)
        if agent_type == "plan_solve":
            return PlanAndSolveAgent(**common)
        if agent_type == "reflection":
            return ReflectionAgent(**common)
        # Should be unreachable thanks to the type system, but keep it safe.
        raise ValueError(f"unknown agent type: {agent_type!r}")

    # --- internals -----------------------------------------------------------

    def _classify_with_llm(self, user_message: str) -> RouteDecision | None:
        """Single-shot LLM classification. Returns None on any failure."""
        prompt = self.classifier_prompt.format(prompt=user_message)
        try:
            response = self.llm.chat(
                messages=[Message(role=Role.USER, content=prompt)],
                tools=None,
                temperature=0.0,
                max_tokens=120,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort; fallback handles it
            logger.debug("TaskRouter: LLM classify failed: {}", exc)
            return None

        raw = response.choices[0].message.content or ""
        parsed = self._parse_llm_label(raw)
        if parsed is None:
            return None
        label, reason = parsed
        return RouteDecision(
            agent_type=label,
            source="llm",
            reason=reason or "LLM classifier",
            raw=raw,
        )

    def _classify_with_rules(self, user_message: str) -> RouteDecision:
        """Heuristic fallback when the LLM tier is unavailable."""
        msg = user_message.strip()
        lower = msg.lower()

        # --- plan_solve: explicit planning / multi-step language ---
        plan_solve_patterns: tuple[str, ...] = (
            r"step[ -]by[ -]step",
            r"first .* then ",
            r"\bplan:",
            r"\bplan to\b",
            r"\bsub-?task",
            r"in order to",
        )
        if any(re.search(pat, lower) for pat in plan_solve_patterns):
            return RouteDecision(
                agent_type="plan_solve",
                source="rule",
                reason="planning / multi-step phrasing detected",
            )

        # --- reflection: review / improve / proofread language ---
        reflection_kw: tuple[str, ...] = (
            "review this",
            "double-check",
            "double check",
            "improve this",
            "proofread",
            "refactor and verify",
            "check for errors",
            "self-critique",
            "before delivering",
        )
        if any(kw in lower for kw in reflection_kw):
            return RouteDecision(
                agent_type="reflection",
                source="rule",
                reason="review / improve phrasing detected",
            )

        # --- simple: very short, no tool-y words, no question mark ---
        tool_kw: tuple[str, ...] = (
            "search",
            "fetch",
            "download",
            "read file",
            "open file",
            "run ",
            "execute",
            "browse",
            "http",
            "www.",
            "https://",
            "http://",
            "shell",
            "powershell",
            "cmd",
        )
        if len(msg) < 60 and not any(kw in lower for kw in tool_kw) and not msg.endswith("?"):
            return RouteDecision(
                agent_type="simple",
                source="rule",
                reason="short prompt with no tool-y keywords",
            )

        # --- default: react (the configured DEFAULT per config.yaml) ---
        return RouteDecision(
            agent_type=self.FALLBACK_LABEL,
            source="rule",
            reason="ambiguous prompt; defaulting to react",
        )

    def _parse_llm_label(self, raw: str) -> tuple[AgentType, str] | None:
        """Parse the LLM classifier's JSON reply into (label, reason)."""
        text = raw.strip()
        if not text:
            return None
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        match = re.search(r"\{.*?\}", text, re.DOTALL)
        candidate = match.group(0) if match else text

        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return self._extract_bare_label(text)

        if isinstance(data, dict):
            label_raw = str(data.get("label", "")).strip().lower()
            reason = str(data.get("reason", "")).strip()
            if label_raw in VALID_AGENT_TYPES:
                return label_raw, reason  # type: ignore[return-value]
        return self._extract_bare_label(text)

    @staticmethod
    def _extract_bare_label(text: str) -> tuple[AgentType, str] | None:
        lower = text.lower()
        for label in VALID_AGENT_TYPES:
            if re.search(rf"\b{re.escape(label)}\b", lower):
                return label, "label keyword matched in raw reply"  # type: ignore[return-value]
        return None
