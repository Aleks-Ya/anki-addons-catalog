import asyncio
import json
import logging
from typing import Any

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import CallToolResult, TextContent

from anki_addons_catalog.domain.errors import CatalogUnavailable
from anki_addons_catalog.domain.models import ToolResult, ToolSpec

log = logging.getLogger(__name__)

RATE_LIMIT_HEADERS = ("RateLimit", "RateLimit-Policy", "Retry-After")  # HF's 429s name the bucket, quota and reset


def _describe(error: BaseException) -> str:
    """The innermost errors of an exception group (anyio wraps transport errors in TaskGroup groups)."""
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(_describe(e) for e in error.exceptions)
    return f"{type(error).__name__}: {error}"


def _to_result(result: CallToolResult) -> ToolResult:
    text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
    structured = result.structured_content
    if structured is not None and set(structured) == {"result"}:
        structured = structured["result"]  # list results are wrapped by MCPServer
    if not text and structured is not None:
        text = json.dumps(structured, ensure_ascii=False)
    return ToolResult(is_error=bool(result.is_error), text=text, structured=structured)


class _Session:
    """Owns one MCP client in a dedicated task: anyio requires a context to be exited by the task that entered it,
    while requests come from many request-handler tasks."""

    def __init__(self, server: str | MCPServer, timeout_seconds: float, headers: dict[str, str] | None) -> None:
        self._server = server
        self._timeout = timeout_seconds
        self._headers = headers
        self._ready: asyncio.Future[Client] = asyncio.get_running_loop().create_future()
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="mcp-session")

    async def _run(self) -> None:
        try:
            if isinstance(self._server, str) and self._headers:
                async with create_mcp_http_client(headers=self._headers) as http:
                    await self._serve(Client(streamable_http_client(self._server, http_client=http),
                                             read_timeout_seconds=self._timeout))
            else:
                await self._serve(Client(self._server, read_timeout_seconds=self._timeout))
        except Exception as e:
            if not self._ready.done():
                self._ready.set_exception(e)
            else:
                log.debug("MCP session ended with an error", exc_info=True)

    async def _serve(self, client: Client) -> None:
        async with client:
            self._ready.set_result(client)
            await self._stop.wait()

    async def client(self) -> Client:
        return await asyncio.shield(self._ready)

    async def close(self) -> None:
        self._stop.set()
        await asyncio.gather(self._task, return_exceptions=True)


class McpCatalog:
    """CatalogPort over one long-lived MCP client session, reconnected when a call fails.

    `server` is the MCP endpoint URL, or an in-process MCPServer in tests. `headers` go with every HTTP request
    (the HF token, see `bootstrap.mcp_auth_headers`: anonymous requests from a Space share its IP's rate limit and
    get HTTP 429).
    """

    def __init__(self, server: str | MCPServer, timeout_seconds: float = 120.0,
                 headers: dict[str, str] | None = None) -> None:
        self._server = server
        self._timeout = timeout_seconds
        self._headers = headers or {}
        self._session: _Session | None = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> Client:
        async with self._lock:
            if self._session is None:
                self._session = _Session(self._server, self._timeout, self._headers)
            session = self._session
        try:
            return await session.client()
        except Exception as e:
            await self._reset(session)
            raise CatalogUnavailable(f"Cannot connect to the MCP server: {_describe(e)}"
                                     f"{await self._probe()}") from e

    async def _reset(self, session: _Session | None = None) -> None:
        async with self._lock:
            current = self._session
            if current is None or (session is not None and current is not session):
                return
            self._session = None
        await current.close()

    async def close(self) -> None:
        await self._reset()

    async def _with_retry[T](self, operation: str, call: Any) -> T:
        for attempt in (1, 2):
            client = await self._connect()
            try:
                return await call(client)  # type: ignore[no-any-return]
            except CatalogUnavailable:
                raise
            except Exception as e:
                log.warning("MCP %s failed (attempt %d): %s", operation, attempt, _describe(e))
                await self._reset()
                if attempt == 2:
                    raise CatalogUnavailable(f"MCP {operation} failed: {_describe(e)}") from e
        raise AssertionError("unreachable")

    async def list_tools(self) -> list[ToolSpec]:
        async def call(client: Client) -> list[ToolSpec]:
            tools = (await client.list_tools()).tools
            return [ToolSpec(name=t.name, description=t.description or "", input_schema=dict(t.input_schema))
                    for t in tools]
        return await self._with_retry("list_tools", call)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        async def call(client: Client) -> ToolResult:
            return _to_result(await client.call_tool(name, arguments))
        return await self._with_retry(f"call_tool({name})", call)

    async def _probe(self) -> str:
        """A plain HTTP request to the endpoint, to show what a failing server or proxy actually returns."""
        if not isinstance(self._server, str):
            return ""
        request = {"jsonrpc": "2.0", "id": 0, "method": "ping"}
        headers = {"Accept": "application/json, text/event-stream", **self._headers}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as http:
                response = await http.post(self._server, json=request, headers=headers)
            limits = "".join(f", {name}: {response.headers[name]}" for name in RATE_LIMIT_HEADERS
                             if name in response.headers)
            return f" (probe: HTTP {response.status_code}{limits}: {response.text[:300]!r})"
        except httpx.HTTPError as e:
            return f" (probe: {_describe(e)})"

    async def ping(self) -> bool:
        """Wakes up the MCP Space through its /healthz endpoint (cheaper than an MCP request)."""
        if not isinstance(self._server, str):
            return True
        url = self._server.rsplit("/", 1)[0] + "/healthz"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers) as http:
                return (await http.get(url)).status_code == 200
        except httpx.HTTPError as e:
            log.warning("MCP keep-alive ping failed: %s", e)
            return False
