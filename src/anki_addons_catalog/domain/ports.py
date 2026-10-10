from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from anki_addons_catalog.domain.models import LlmTurn, ToolResult, ToolSpec


class CatalogPort(Protocol):
    """Access to the Anki Addons MCP server."""

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...

    async def ping(self) -> bool: ...


TextCallback = Callable[[str], Awaitable[None]]


class LlmPort(Protocol):
    """A language model that answers with text and tool calls."""

    async def turn(self, system: str, tools: list[ToolSpec], messages: list[dict[str, Any]],
                   on_text: TextCallback) -> LlmTurn: ...
