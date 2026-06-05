"""OpenAI-compatible LLM client.

Wraps the official `openai` SDK. Both sync and async paths. Streaming is supported.
Provider auto-detection is best-effort (purely for log labels).

Note: this module imports openai lazily inside __init__-like helpers where possible
to keep `hello-agent doctor` import-cheap.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, OpenAI
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from hello_agent.core.config import get_env
from hello_agent.core.logging import get_logger
from hello_agent.core.types import Message, ToolDefinition

logger = get_logger(__name__)


# Retryable error tuple — only transient infra failures, NOT 4xx.
_RETRY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    APIConnectionError,
    APITimeoutError,
    TimeoutError,
    ConnectionError,
)


def _message_to_openai_dict(msg: Message) -> dict[str, Any]:
    """Convert our Message to the dict shape the openai SDK wants."""
    out: dict[str, Any] = {"role": msg.role.value}
    if msg.content is not None:
        out["content"] = msg.content
    if msg.tool_calls is not None:
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id is not None:
        out["tool_call_id"] = msg.tool_call_id
    if msg.name is not None:
        out["name"] = msg.name
    return out


def _tool_def_to_openai_dict(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


class LLMClient:
    """Sync + async OpenAI-compatible LLM client."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
    ) -> None:
        env = get_env()
        self.base_url = (base_url or env.llm_base_url).rstrip("/")
        self.api_key = api_key or env.llm_api_key
        self.model = model or env.llm_model
        self.timeout = timeout_seconds or env.llm_timeout_seconds
        self.max_retries = max_retries or env.llm_max_retries

        # Defer client construction until first call to avoid import-time failures
        # for users running `hello-agent doctor` without a key.
        self._sync: OpenAI | None = None
        self._async: AsyncOpenAI | None = None

    # --- public helpers ---

    @staticmethod
    def _sanitize_key(key: str) -> str:
        if not key:
            raise ValueError(
                "LLM_API_KEY is empty. Set it in .env or via env var. "
                "Run `hello-agent doctor` for the full env checklist."
            )
        return key

    @property
    def provider_name(self) -> str:
        """Best-effort provider name from base_url, for log labels only."""
        url = self.base_url.lower()
        if "deepseek" in url:
            return "deepseek"
        if "bigmodel" in url or "zhipu" in url:
            return "zhipu"
        if "moonshot" in url or "kimi" in url:
            return "moonshot"
        if "ollama" in url or "localhost" in url or "127.0.0.1" in url:
            return "local"
        if "openai.com" in url:
            return "openai"
        return "unknown"

    def _ensure_sync(self) -> OpenAI:
        if self._sync is None:
            self._sync = OpenAI(
                base_url=self.base_url,
                api_key=self._sanitize_key(self.api_key),
                timeout=self.timeout,
                max_retries=0,  # we handle retries ourselves
            )
        return self._sync

    def _ensure_async(self) -> AsyncOpenAI:
        if self._async is None:
            self._async = AsyncOpenAI(
                base_url=self.base_url,
                api_key=self._sanitize_key(self.api_key),
                timeout=self.timeout,
                max_retries=0,
            )
        return self._async

    # --- sync chat ---

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
        reraise=True,
    )
    def _chat_with_retry(self, **kwargs: Any) -> ChatCompletion:
        client = self._ensure_sync()
        return client.chat.completions.create(**kwargs)

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> ChatCompletion | Iterator[ChatCompletionChunk]:
        """Sync chat completion. With stream=True returns an iterator."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_openai_dict(m) for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [_tool_def_to_openai_dict(t) for t in tools]
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        logger.bind(category="llm").debug(
            "LLM call model={} messages={} tools={} stream={}",
            self.model,
            len(messages),
            len(tools) if tools else 0,
            stream,
        )

        client = self._ensure_sync()
        if stream:
            return client.chat.completions.create(**payload)

        return self._chat_with_retry(**payload)

    # --- async chat ---

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        retry=retry_if_exception_type(_RETRY_EXCEPTIONS),
        reraise=True,
    )
    async def _achat_with_retry(self, **kwargs: Any) -> ChatCompletion:
        client = self._ensure_async()
        return await client.chat.completions.create(**kwargs)

    async def achat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> ChatCompletion | AsyncIterator[ChatCompletionChunk]:
        """Async chat completion. With stream=True returns an async iterator."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_openai_dict(m) for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        if tools:
            payload["tools"] = [_tool_def_to_openai_dict(t) for t in tools]
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        client = self._ensure_async()
        if stream:
            return await client.chat.completions.create(**payload)

        return await self._achat_with_retry(**payload)

    # --- token counting (delegates to context/token_counter when available) ---

    def count_tokens(self, messages: list[Message]) -> int:
        try:
            from hello_agent.context.token_counter import count_tokens

            return count_tokens(messages, model=self.model)
        except Exception as exc:  # noqa: BLE001 — best-effort fallback
            logger.debug("token_counter not available, using heuristic: {}", exc)
            # Rough heuristic: 4 chars per token.
            total = 0
            for m in messages:
                if m.content:
                    total += len(m.content) // 4
                if m.tool_calls:
                    total += sum(len(json.dumps(tc.arguments)) // 4 for tc in m.tool_calls)
            return total
