from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from anki_addons_catalog.domain.models import LlmTurn, ToolResult, ToolSpec, Usage


class CatalogPort(Protocol):
    """Access to the Anki Addons MCP server."""

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult: ...

    async def ping(self) -> bool: ...

    async def server_version(self) -> str | None: ...


TextCallback = Callable[[str], Awaitable[None]]
UsageCallback = Callable[[Usage], None]


class LlmPort(Protocol):
    """A language model that answers with text and tool calls."""

    async def turn(self, system: str, tools: list[ToolSpec], messages: list[dict[str, Any]],
                   on_text: TextCallback, on_cancel: UsageCallback | None = None) -> LlmTurn:
        """One model call. When it is cancelled, `on_cancel` gets the usage the model reported so far, if any."""
        ...
