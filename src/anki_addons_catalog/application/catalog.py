import json
from typing import Any

from anki_addons_catalog.application.limits import TtlCache
from anki_addons_catalog.domain.errors import ToolFailed
from anki_addons_catalog.domain.ports import CatalogPort

TOP_METRICS = {
    "rating": "Highest rated", "likes": "Most liked", "stars": "Most GitHub stars",
    "forum_posts": "Most discussed on the Anki Forum", "recently_updated": "Recently updated",
}
STAT_GROUPS = ["license", "primary_language", "description_language", "anki_version", "update_year", "ai_tag"]
OBSOLETE_TAG = "obsolete"


class CatalogService:
    """Plain (non-AI) catalog queries over the MCP tools, with a TTL cache in front."""

    def __init__(self, catalog: CatalogPort, cache_ttl_seconds: float = 3600) -> None:
        self._catalog = catalog
        self._cache: TtlCache[str, Any] = TtlCache(cache_ttl_seconds, max_entries=2000)

    async def call(self, tool: str, **arguments: Any) -> Any:
        key = tool + json.dumps(arguments, sort_keys=True, default=str)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        result = await self._catalog.call_tool(tool, arguments)
        if result.is_error:
            raise ToolFailed(tool, result.text)
        self._cache.put(key, result.structured)
        return result.structured

    async def search(self, query: str, limit: int = 30, offset: int = 0,
                     anki_version: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"query": query, "limit": limit, "offset": offset}
        if anki_version:
            args["compatible_with_anki"] = anki_version
        page: dict[str, Any] = await self.call("search_addons", **args)
        return page

    async def top(self, metric: str = "rating", limit: int = 10) -> dict[str, Any]:
        page: dict[str, Any] = await self.call("top_addons", metric=metric, limit=limit)
        return page

    async def addon(self, addon_id: int) -> dict[str, Any]:
        details: dict[str, Any] = await self.call("get_addon", addon_id=addon_id, include=["links"])
        return details

    async def readme(self, addon_id: int) -> str | None:
        text: dict[str, Any] = await self.call("get_addon_readme", addon_id=addon_id, max_chars=60000)
        readme: str | None = text.get("text")
        return readme

    async def description(self, addon_id: int) -> str | None:
        text: dict[str, Any] = await self.call("get_addon_description", addon_id=addon_id, max_chars=20000)
        description: str | None = text.get("text")
        return description

    async def maintenance(self, addon_id: int) -> dict[str, Any]:
        report: dict[str, Any] = await self.call("assess_maintenance", addon_id=addon_id)
        return report

    async def similar(self, addon_id: int, limit: int = 6) -> list[dict[str, Any]]:
        similar: list[dict[str, Any]] = await self.call("find_similar_addons", addon_id=addon_id, limit=limit)
        return similar

    async def history(self, addon_id: int) -> dict[str, Any]:
        history: dict[str, Any] = await self.call("get_addon_history", addon_id=addon_id)
        return history

    async def compatibility(self, addon_id: int, anki_version: str) -> dict[str, Any]:
        verdicts: list[dict[str, Any]] = await self.call("check_compatibility", addon_ids=[addon_id],
                                                         anki_version=anki_version)
        return verdicts[0]

    async def by_author(self, github_user: str) -> dict[str, Any]:
        page: dict[str, Any] = await self.call("list_addons_by_author", github_user=github_user)
        return page

    async def statistics(self) -> dict[str, Any]:
        stats: dict[str, Any] = await self.call("get_statistics", group_by=STAT_GROUPS, top_values=15)
        return stats

    async def tags(self) -> list[dict[str, Any]]:
        tags: list[dict[str, Any]] = await self.call("list_tags")
        return tags

    async def tag(self, name: str) -> dict[str, Any] | None:
        return next((t for t in await self.tags() if t["name"] == name), None)

    async def by_tag(self, name: str, limit: int = 30, offset: int = 0) -> dict[str, Any]:
        """Addons with an AI tag, best rated first; obsolete addons are hidden unless the tag itself is obsolete."""
        args: dict[str, Any] = {"tags": [name], "sort_by": "rating", "limit": limit, "offset": offset}
        if name != OBSOLETE_TAG:
            args["exclude_tags"] = [OBSOLETE_TAG]
        page: dict[str, Any] = await self.call("filter_addons", **args)
        return page

    async def changes(self, limit: int = 30) -> dict[str, Any]:
        diff: dict[str, Any] = await self.call("diff_snapshots", limit=limit)
        return diff

    async def snapshots(self) -> list[dict[str, Any]]:
        snapshots: list[dict[str, Any]] = await self.call("list_snapshots")
        return snapshots

    async def latest_snapshot_info(self) -> dict[str, Any] | None:
        return next((s for s in await self.snapshots() if s.get("latest")), None)

    async def latest_snapshot(self) -> str | None:
        info = await self.latest_snapshot_info()
        return info["date"] if info else None

    async def dataset_date(self) -> str | None:
        """The day the latest dataset's data was collected (YYYY-MM-DD)."""
        return await self.latest_snapshot()

    async def all_addon_ids(self) -> list[int]:
        """Every addon id of the latest snapshot, for the sitemap."""
        ids: list[int] = []
        offset = 0
        while True:
            page = await self.call("filter_addons", sort_by="rating", limit=100, offset=offset)
            ids.extend(item["id"] for item in page["items"])
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                return ids
