import logging
from typing import Any, Literal

import anthropic

from anki_addons_catalog.domain.models import LlmTurn, StopReason, ToolCall, ToolSpec, Usage
from anki_addons_catalog.domain.ports import TextCallback

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
_STOP_REASONS: set[str] = {"end_turn", "tool_use", "max_tokens", "refusal", "pause_turn"}
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeLlm:
    """LlmPort over the Anthropic Messages API (streaming, adaptive thinking, prompt caching)."""

    def __init__(self, client: anthropic.AsyncAnthropic, model: str, effort: Effort, max_tokens: int,
                 fallbacks_enabled: bool = True) -> None:
        self._client = client
        self._model = model
        self._effort: Effort = effort
        self._max_tokens = max_tokens
        self._fallbacks_enabled = fallbacks_enabled

    @staticmethod
    def tool_params(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Tool definitions in a stable order; the last one carries the cache breakpoint for tools + system."""
        params: list[dict[str, Any]] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in sorted(tools, key=lambda t: t.name)
        ]
        if params:
            params[-1]["cache_control"] = {"type": "ephemeral"}
        return params

    async def turn(self, system: str, tools: list[ToolSpec], messages: list[dict[str, Any]],
                   on_text: TextCallback) -> LlmTurn:
        extra: dict[str, Any] = {}
        if self._fallbacks_enabled:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
        async with self._client.beta.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=self.tool_params(tools),  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
            output_config={"effort": self._effort},
            **extra,
        ) as stream:
            async for event in stream:
                if event.type == "text":
                    await on_text(event.text)
            message = await stream.get_final_message()

        stop_reason: StopReason = message.stop_reason if message.stop_reason in _STOP_REASONS else "other"  # type: ignore[assignment]
        text = "".join(block.text for block in message.content if block.type == "text")
        calls = [ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                 for block in message.content if block.type == "tool_use" and isinstance(block.input, dict)]
        u = message.usage
        usage = Usage(input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                      cache_read_input_tokens=u.cache_read_input_tokens or 0,
                      cache_creation_input_tokens=u.cache_creation_input_tokens or 0)
        log.info("Claude turn: model=%s stop=%s in=%d out=%d cache_read=%d cache_write=%d", message.model,
                 stop_reason, usage.input_tokens, usage.output_tokens, usage.cache_read_input_tokens,
                 usage.cache_creation_input_tokens)
        return LlmTurn(assistant_content=message.content, text=text, tool_calls=calls, stop_reason=stop_reason, usage=usage)
