from datetime import UTC, date, datetime
from typing import Any

from anki_addons_mcp.adapters.memory.repository import InMemoryAddonRepository
from anki_addons_mcp.application.services import build_services
from anki_addons_mcp.domain.compatibility import to_point
from anki_addons_mcp.domain.models import AddonDetails, SnapshotInfo, Tag
from anki_addons_mcp.interface.mcp.server import build_server
from mcp.server.mcpserver import MCPServer

KANJI = 1001
OCCLUSION = 1002
HEATMAP = 1003
OLD = date(2026, 8, 1)
LATEST = date(2026, 9, 1)
LATEST_CREATED = datetime(2026, 9, 3, 4, 5, tzinfo=UTC)
TAGS = [
    Tag(name="dictionary", group="function", description="Lookup, definitions, translation"),
    Tag(name="image-occlusion", group="function", description="Image occlusion"),
    Tag(name="statistics", group="function", description="Graphs, heatmaps, retention"),
    Tag(name="obsolete", group="status", description="Built into Anki now, or no longer working"),
    Tag(name="paid", group="status", description="Patreon-only, Pro tiers, subscriptions"),
]


def _addon(addon_id: int, title: str, *, rating: int, update_date: str, anki_version: str, summary: str,
           description: str, tags: list[str], user: str | None = None, stars: int = 0,
           readme: str | None = None) -> AddonDetails:
    record: dict[str, Any] = {
        "id": addon_id,
        "anki_web": {
            "title": title, "addon_page_url": f"https://ankiweb.net/shared/info/{addon_id}", "rating": rating,
            "likes": rating + 2, "dislikes": 2, "update_date": update_date, "anki_version": anki_version,
            "anki_point_version": to_point(anki_version), "anki_version_kind": "tested",
            "branches": [{"min_version": anki_version.rstrip("~"), "max_version": "+", "updated": update_date,
                          "min_point_version": to_point(anki_version), "max_version_kind": "open"}],
            "links": [{"url": f"https://example.com/{addon_id}", "section": "description", "count": 1,
                       "texts": ["site"]}], "description_language": "en",
        },
        "github": {
            "user": user, "repo": title.lower().replace(" ", "-"), "stars": stars, "license": "MIT",
            "last_commit": update_date + "T10:00:00", "languages": ["Python"], "tests_count": 3, "forks": 1,
            "open_issues": 0, "topics": [title.split()[0].lower()],
        } if user else None,
        "ai": {"summary": summary, "tags": tags},
        "description": description,
        "readme": readme,
    }
    return AddonDetails.model_validate(record)


def latest_addons() -> list[AddonDetails]:
    return [
        _addon(KANJI, "Kanji Helper", rating=120, update_date="2026-08-20", anki_version="25.02~",
               summary="Shows kanji stroke order.", description="Kanji stroke order and readings.", tags=["dictionary"],
               user="alice", stars=50, readme="# Kanji Helper\n\n<script>alert(1)</script>\n\nSee [docs](https://x.org), [manual](docs/manual.md), [top](#usage).\n\n![shot](img/a.png)"),
        _addon(OCCLUSION, "Image Occlusion Plus", rating=300, update_date="2026-08-01", anki_version="2.1.66~",
               summary="Creates image occlusion cards.", description="Hide parts of an image.", tags=["image-occlusion"], user="bob",
               stars=500),
        _addon(HEATMAP, "Review Heatmap", rating=80, update_date="2024-01-10", anki_version="2.1.20~",
               summary="Heatmap of reviews.", description="Heatmap of review history.",
               tags=["statistics", "obsolete"]),
    ]


def mcp_server() -> MCPServer:
    snapshots = {OLD: latest_addons()[1:], LATEST: latest_addons()}
    infos = {d: SnapshotInfo(date=d, latest=d == LATEST, report_generation_date=LATEST_CREATED if d == LATEST else None)
             for d in snapshots}
    tags = {d: TAGS for d in snapshots}
    return build_server(build_services(InMemoryAddonRepository(snapshots, infos, tags=tags)))
