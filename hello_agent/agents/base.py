"""Agent ABC + AgentState dataclass."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from hello_agent.core.types import AgentState, Message, Role


def _generate_session_id() -> str:
    return str(uuid.uuid4())


class Agent(ABC):
    """Base class for all agent types. Subclasses override `step()`."""

    def __init__(
        self,
        system_prompt: str,
        max_iterations: int = 30,
        max_cost_per_turn_usd: float = 0.50,
        session_id: str | None = None,
    ):
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.max_cost_per_turn_usd = max_cost_per_turn_usd
        self.session_id = session_id or _generate_session_id()

    @abstractmethod
    def step(self, state: AgentState) -> AgentState:
        """One step of the agent loop. Subclasses define the strategy."""
        raise NotImplementedError

    def run(self, user_message: str) -> AgentState:
        """Main entry: take user message, run loop until done, return final state."""
        state = AgentState(
            session_id=self.session_id,
            messages=[
                Message(role=Role.SYSTEM, content=self.system_prompt),
                Message(role=Role.USER, content=user_message),
            ],
            max_iterations=self.max_iterations,
            max_cost_per_turn_usd=self.max_cost_per_turn_usd,
        )
        while state.iteration < state.max_iterations:
            if state.interrupted:
                break
            state = self.step(state)
            state.iteration += 1
            if self._is_terminal(state):
                break
        return state

    def _is_terminal(self, state: AgentState) -> bool:
        """Default terminal: last message is assistant with no tool calls."""
        if not state.messages:
            return True
        last = state.messages[-1]
        return last.role == Role.ASSISTANT and not last.tool_calls
