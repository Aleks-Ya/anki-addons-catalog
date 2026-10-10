from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from anki_addons_catalog.adapters.mcp.catalog import McpCatalog
from anki_addons_catalog.domain.models import LlmTurn, ToolSpec
from anki_addons_catalog.domain.ports import TextCallback
from tests.fixtures import mcp_server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def server() -> MCPServer:
    return mcp_server()


@pytest.fixture
async def catalog(server: MCPServer) -> AsyncIterator[McpCatalog]:
    catalog = McpCatalog(server, timeout_seconds=10)
    yield catalog
    await catalog.close()


class FakeLlm:
    """Replays scripted turns and records the requests."""

    def __init__(self, turns: list[LlmTurn]) -> None:
        self.turns = list(turns)
        self.requests: list[list[dict[str, Any]]] = []
        self.tools: list[ToolSpec] = []

    async def turn(self, system: str, tools: list[ToolSpec], messages: list[dict[str, Any]],
                   on_text: TextCallback) -> LlmTurn:
        self.requests.append([dict(m) for m in messages])
        self.tools = tools
        turn = self.turns.pop(0)
        if turn.text:
            await on_text(turn.text)
        return turn


@pytest.fixture
def fake_llm() -> Iterator[FakeLlm]:
    yield FakeLlm([])
