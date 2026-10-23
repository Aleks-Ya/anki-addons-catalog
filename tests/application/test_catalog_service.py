from typing import Any

import pytest

from anki_addons_catalog.adapters.mcp.catalog import McpCatalog
from anki_addons_catalog.application.catalog import CatalogService
from anki_addons_catalog.domain.errors import ToolFailed
from anki_addons_catalog.domain.models import SearchFilters, ToolResult
from tests.fixtures import FORK, HEATMAP, KANJI, OCCLUSION

pytestmark = pytest.mark.anyio


class CountingCatalog:
    def __init__(self, inner: McpCatalog) -> None:
        self.inner = inner
        self.calls: list[str] = []

    async def list_tools(self) -> Any:
        return await self.inner.list_tools()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(name)
        return await self.inner.call_tool(name, arguments)

    async def ping(self) -> bool:
        return True

    async def server_version(self) -> str | None:
        return await self.inner.server_version()


@pytest.fixture
def counting(catalog: McpCatalog) -> CountingCatalog:
    return CountingCatalog(catalog)


async def test_search_and_top(counting: CountingCatalog) -> None:
    service = CatalogService(counting)
    assert [c["id"] for c in (await service.search("kanji"))["items"]] == [KANJI]
    assert [c["id"] for c in (await service.top("rating", 2))["items"]] == [OCCLUSION, KANJI]


async def test_results_are_cached(counting: CountingCatalog) -> None:
    service = CatalogService(counting)
    await service.addon(KANJI)
    await service.addon(KANJI)
    assert counting.calls == ["get_addon"]


async def test_addon_page_data(counting: CountingCatalog) -> None:
    service = CatalogService(counting)
    assert (await service.addon(KANJI))["anki_web"]["title"] == "Kanji Helper"
    assert (await service.readme(KANJI) or "").startswith("# Kanji Helper")
    assert (await service.maintenance(KANJI))["label"]
    assert isinstance(await service.similar(KANJI), list)
    assert (await service.compatibility(KANJI, "25.02"))["verdict"] == "supported"
    assert len((await service.history(OCCLUSION))["points"]) == 2


async def test_unknown_addon_raises(counting: CountingCatalog) -> None:
    with pytest.raises(ToolFailed, match="get_addon"):
        await CatalogService(counting).addon(42)


async def test_snapshots_stats_changes(counting: CountingCatalog) -> None:
    service = CatalogService(counting)
    assert await service.latest_snapshot() == "2026-09-01"
    assert (await service.statistics())["aggregation"]["addon_number"] == 4
    assert await service.addon_count() == 4
    assert [c["id"] for c in (await service.changes())["added"]] == [KANJI]
    assert sorted(await service.all_addon_ids()) == [KANJI, OCCLUSION, HEATMAP, FORK]
    assert [c["id"] for c in (await service.by_author("bob"))["items"]] == [OCCLUSION]


async def test_search_and_browse_with_filters(counting: CountingCatalog) -> None:
    service = CatalogService(counting)
    assert [c["id"] for c in (await service.search("heatmap"))["items"]] == [FORK]  # obsolete hidden by default
    assert {c["id"] for c in (await service.search("heatmap", SearchFilters(show_obsolete=True)))["items"]} == {
        HEATMAP, FORK}
    assert (await service.search("heatmap", SearchFilters(hide_forks=True)))["total"] == 0
    browse = await service.browse(SearchFilters(show_obsolete=True, sort="update_date"))
    assert [c["id"] for c in browse["items"]] == [KANJI, OCCLUSION, FORK, HEATMAP]
    assert [c["id"] for c in (await service.browse(SearchFilters(min_rating=200)))["items"]] == [OCCLUSION]
    old_anki = await service.browse(SearchFilters(anki="2.1.50", show_obsolete=True))
    assert [c["id"] for c in old_anki["items"]] == [HEATMAP]


async def test_forks(counting: CountingCatalog) -> None:
    service = CatalogService(counting)
    assert [c["id"] for c in (await service.forks(HEATMAP))["items"]] == [FORK]
    assert (await service.forks(KANJI))["items"] == []


async def test_anki_versions_newest_first(counting: CountingCatalog) -> None:
    service = CatalogService(counting)
    assert await service.anki_versions() == ["25.09.2", "25.09", "2.1.66"]
    await service.anki_versions()
    assert counting.calls == ["list_anki_versions"]
