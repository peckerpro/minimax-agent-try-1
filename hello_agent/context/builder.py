"""ContextBuilder — assemble system + history + RAG + memory recall into the
final LLM prompt.

Order (Day-4 spec, ENGINEERING.md §6.5):

  1. system_prompt
  2. memory_chunks   (as "system note" messages before history, with
                     cache_breakpoint=True so repeated turns re-use the prefix)
  3. past messages   (from `AgentState.messages`; skip the leading system
                     message that we already emitted)
  4. RAG chunks      (a final system message with the relevant docs joined)

Token budget:

- `context.max_context_tokens`      total budget (default 128_000)
- `context.response_reserve_tokens` reserved for the LLM's reply (default 4_000)
- Effective prompt budget = max_context_tokens - response_reserve_tokens

If the assembled prompt exceeds the effective budget, `build()` will call
`ObservationTruncator` on the largest tool-output messages first (cheapest
preserves the most signal), and if that isn't enough, drop the oldest
non-compressed non-system messages until we fit.

Public API:

- `ContextBuilder(max_context_tokens=..., response_reserve_tokens=...)`
- `ContextBuilder.build(state, available_tools=..., memory_chunks=...,
                        rag_chunks=..., system_prompt=...) -> list[Message]`
- `build_prompt(state, ...)` — module-level convenience for back-compat.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from hello_agent.context.truncator import ObservationTruncator
from hello_agent.core.types import AgentState, Message, Role

if TYPE_CHECKING:
    from hello_agent.core.types import ToolDefinition

_DEFAULT_MAX_CONTEXT_TOKENS = 128_000
_DEFAULT_RESPONSE_RESERVE_TOKENS = 4_000


def _budget_from_config() -> tuple[int, int]:
    """Read context budget from `config.context`; fall back to defaults."""
    try:
        from hello_agent.core.config import HelloAgentConfig, get_config

        cfg: HelloAgentConfig = get_config()
        ctx = cfg.context
        return (
            int(ctx.max_context_tokens) or _DEFAULT_MAX_CONTEXT_TOKENS,
            int(ctx.response_reserve_tokens) or _DEFAULT_RESPONSE_RESERVE_TOKENS,
        )
    except Exception:  # noqa: BLE001
        return _DEFAULT_MAX_CONTEXT_TOKENS, _DEFAULT_RESPONSE_RESERVE_TOKENS


def _count_text_chars(messages: list[Message]) -> int:
    """Cheap char-based budget estimate. The LLM call will use tiktoken.

    Used by the builder to decide whether to truncate without paying the
    tiktoken encode cost for every turn.
    """
    total = 0
    for m in messages:
        if m.content:
            total += len(m.content)
        if m.tool_calls:
            for tc in m.tool_calls:
                total += len(tc.name) + len(str(tc.arguments) if tc.arguments else "")
    return total


class ContextBuilder:
    """Stateless assembler for the LLM prompt.

    Holds two pieces of state (the budget limits); everything else is a
    pure function of the inputs. Agents call `.build(...)` once per turn.
    """

    __slots__ = (
        "max_context_tokens",
        "response_reserve_tokens",
        "_truncator",
    )

    def __init__(
        self,
        max_context_tokens: int | None = None,
        response_reserve_tokens: int | None = None,
        truncator: ObservationTruncator | None = None,
    ) -> None:
        cfg_max, cfg_reserve = _budget_from_config()
        self.max_context_tokens: int = (
            max_context_tokens if max_context_tokens is not None else cfg_max
        )
        self.response_reserve_tokens: int = (
            response_reserve_tokens if response_reserve_tokens is not None else cfg_reserve
        )
        if self.max_context_tokens < 1 or self.response_reserve_tokens < 1:
            raise ValueError(
                "max_context_tokens and response_reserve_tokens must be >= 1"
            )
        if self.response_reserve_tokens >= self.max_context_tokens:
            raise ValueError(
                "response_reserve_tokens must be strictly less than max_context_tokens"
            )
        self._truncator = truncator or ObservationTruncator()

    @property
    def effective_prompt_tokens(self) -> int:
        """The budget available to the prompt itself (excludes the reserve)."""
        return self.max_context_tokens - self.response_reserve_tokens

    # --- public ---------------------------------------------------------

    def build(
        self,
        state: AgentState,
        available_tools: list[ToolDefinition] | None = None,
        memory_chunks: list[str] | None = None,
        rag_chunks: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> list[Message]:
        """Assemble the final list of messages to send to the LLM.

        Returns a *new* list — does not mutate `state.messages`.
        """
        out: list[Message] = []

        # 1. System prompt
        if system_prompt is None:
            system_prompt = state.messages[0].content if state.messages else None
        if system_prompt:
            out.append(Message(role=Role.SYSTEM, content=system_prompt, system=True))

        # 2. Memory chunks — also as system messages, with cache_breakpoint=True
        #    so prefix caching survives across turns.
        for chunk in memory_chunks or []:
            out.append(
                Message(
                    role=Role.SYSTEM,
                    content=f"[memory recall]\n{chunk}",
                    cache_breakpoint=True,
                    system=True,
                )
            )

        # 3. Past messages — skip the leading system message we already emitted.
        for m in state.messages:
            if m.role == Role.SYSTEM:
                continue
            out.append(m)

        # 4. RAG chunks — final system message with the relevant documents.
        if rag_chunks:
            joined = "\n\n---\n\n".join(rag_chunks)
            out.append(
                Message(
                    role=Role.SYSTEM,
                    content=f"[relevant documents]\n{joined}",
                    system=True,
                )
            )

        # Budget enforcement: truncate tool outputs first, then drop oldest
        # non-compressed history messages until we fit.
        return self._enforce_budget(out)

    # --- internal budget helpers -----------------------------------------

    def _enforce_budget(self, messages: list[Message]) -> list[Message]:
        """Shrink `messages` until they fit in `self.effective_prompt_tokens`.

        Strategy:
        1. If the rough char-based estimate fits, return as-is. (Avoids the
           cost of a tiktoken encode for the common case.)
        2. Otherwise, call `ObservationTruncator` on every tool-role message
           with content longer than the per-line budget.
        3. If still over budget, drop oldest non-system, non-compressed
           messages until we fit.
        """
        if _count_text_chars(messages) <= self.effective_prompt_tokens * 4:
            return messages

        # 1) Truncate long tool messages.
        result: list[Message] = []
        for m in messages:
            if m.role == Role.TOOL and m.content and m.content.count("\n") > 50:
                result.append(self._truncator.truncate(m, max_lines=70))
            else:
                result.append(m)
        if _count_text_chars(result) <= self.effective_prompt_tokens * 4:
            return result

        # 2) Drop oldest non-system, non-compressed messages until we fit.
        # We keep a single leading system message if one exists.
        head: list[Message] = []
        if result and result[0].role == Role.SYSTEM:
            head.append(result[0])
            middle = list(result[1:])
        else:
            middle = list(result)
        # Drop from the front of `middle`, preserving order.
        while middle and _count_text_chars(head + middle) > self.effective_prompt_tokens * 4:
            # Find the first droppable message.
            drop_idx = -1
            for i, m in enumerate(middle):
                if m.role == Role.SYSTEM:
                    continue
                if m.compressed:
                    continue
                drop_idx = i
                break
            if drop_idx < 0:
                # Nothing left to drop; break to avoid an infinite loop.
                break
            del middle[drop_idx]
        return head + middle


def build_prompt(
    state: AgentState,
    available_tools: list[ToolDefinition] | None = None,
    memory_chunks: list[str] | None = None,
    rag_chunks: list[str] | None = None,
    system_prompt: str | None = None,
) -> list[Message]:
    """Module-level convenience wrapper around `ContextBuilder().build(...)`."""
    return ContextBuilder().build(
        state,
        available_tools=available_tools,
        memory_chunks=memory_chunks,
        rag_chunks=rag_chunks,
        system_prompt=system_prompt,
    )
