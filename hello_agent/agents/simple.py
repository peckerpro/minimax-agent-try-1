"""Single-shot LLM call. No tools, no loop. Cheapest agent type."""
from __future__ import annotations

from hello_agent.agents.base import Agent
from hello_agent.core.llm import LLMClient
from hello_agent.core.types import AgentState, Message, Role


class SimpleAgent(Agent):
    """Single-shot LLM call. Useful for quick Q&A without tool overhead."""

    def __init__(
        self,
        llm: LLMClient,
        system_prompt: str = "You are a helpful assistant.",
        max_iterations: int = 1,
        max_cost_per_turn_usd: float = 0.50,
        session_id: str | None = None,
    ):
        super().__init__(
            system_prompt=system_prompt,
            max_iterations=max_iterations,
            max_cost_per_turn_usd=max_cost_per_turn_usd,
            session_id=session_id,
        )
        self.llm = llm

    def step(self, state: AgentState) -> AgentState:
        response = self.llm.chat(
            messages=state.messages,
            tools=None,
        )
        choice = response.choices[0]
        msg = Message(
            role=Role.ASSISTANT,
            content=choice.message.content,
            finish_reason=choice.finish_reason,
            token_count=response.usage.total_tokens if response.usage else None,
        )
        state.messages.append(msg)
        return state
