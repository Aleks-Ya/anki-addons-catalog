import pytest

from anki_addons_catalog.adapters.mcp.catalog import McpCatalog
from anki_addons_catalog.domain.errors import CatalogUnavailable
from tests.fixtures import KANJI, OCCLUSION

pytestmark = pytest.mark.anyio


async def test_lists_tools_with_schemas(catalog: McpCatalog) -> None:
    tools = {t.name: t for t in await catalog.list_tools()}
    assert {"search_addons", "get_addon", "check_compatibility"} <= tools.keys()
    assert tools["search_addons"].input_schema["properties"]["query"]
    assert tools["search_addons"].description


async def test_call_tool_returns_structured_content(catalog: McpCatalog) -> None:
    result = await catalog.call_tool("search_addons", {"query": "kanji"})
    assert not result.is_error
    assert [item["id"] for item in result.structured["items"]] == [KANJI]
    assert '"Kanji Helper"' in result.text


async def test_list_results_are_unwrapped(catalog: McpCatalog) -> None:
    result = await catalog.call_tool("check_compatibility", {"addon_ids": [OCCLUSION], "anki_version": "25.02"})
    assert isinstance(result.structured, list)
    assert result.structured[0]["addon_id"] == OCCLUSION


async def test_tool_error_is_a_result(catalog: McpCatalog) -> None:
    result = await catalog.call_tool("get_addon", {"addon_id": 42})
    assert result.is_error
    assert "42" in result.text


async def test_concurrent_calls_share_one_session(catalog: McpCatalog) -> None:
    import asyncio
    results = await asyncio.gather(*(catalog.call_tool("get_addon", {"addon_id": KANJI}) for _ in range(5)))
    assert all(not r.is_error for r in results)


async def test_unreachable_server_raises() -> None:
    catalog = McpCatalog("http://127.0.0.1:9/mcp", timeout_seconds=2)
    with pytest.raises(CatalogUnavailable):
        await catalog.list_tools()
    assert not await catalog.ping()
    await catalog.close()


async def test_ping_in_process_server(catalog: McpCatalog) -> None:
    assert await catalog.ping()


async def test_ping_sends_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    seen: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    catalog = McpCatalog("https://mcp.example/mcp", headers={"Authorization": "Bearer hf_test"})
    assert await catalog.ping()
    assert str(seen[0].url) == "https://mcp.example/healthz"
    assert seen[0].headers["Authorization"] == "Bearer hf_test"
