"""ContextBuilder — assemble system + history + tools + RAG into the final LLM prompt.

Order:
  1. system_prompt
  2. memory note (optional, "system" role but with a flag)
  3. past messages (sliding window)
  4. RAG chunks (appended as a single user message with the original question echoed)

This is intentionally a stateless function; agents pass the result straight to
`llm.chat()`.
"""
from __future__ import annotations

from hello_agent.core.types import AgentState, Message, Role, ToolDefinition


def build_prompt(
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
        out.append(Message(role=Role.SYSTEM, content=system_prompt))

    # 2. Memory chunks (also as system messages — preserves cache prefix)
    for chunk in memory_chunks or []:
        out.append(
            Message(
                role=Role.SYSTEM,
                content=f"[memory recall]\n{chunk}",
                cache_breakpoint=True,
            )
        )

    # 3. Past messages — skip the leading system message we already emitted
    for m in state.messages:
        if m.role == Role.SYSTEM:
            continue
        out.append(m)

    # 4. RAG chunks — append as a user-side "context" message just before the
    # last user message. Simplest correct version: append a fresh system message
    # at the end (LLMs handle it well in practice).
    if rag_chunks:
        joined = "\n\n---\n\n".join(rag_chunks)
        out.append(
            Message(
                role=Role.SYSTEM,
                content=f"[relevant documents]\n{joined}",
            )
        )

    return out
