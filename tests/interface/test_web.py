import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer

from anki_addons_catalog.adapters.mcp.catalog import McpCatalog
from anki_addons_catalog.bootstrap import create_app
from anki_addons_catalog.config import Settings
from anki_addons_catalog.domain.models import LlmTurn, SearchFilters, ToolCall, Usage
from anki_addons_catalog.interface.web.app import search_url
from anki_addons_catalog.interface.web.security import PASS_COOKIE
from tests.conftest import FakeLlm
from tests.fixtures import HEATMAP, KANJI, OCCLUSION


def settings(**overrides: Any) -> Settings:
    overrides.setdefault("usage_db", ":memory:")
    return Settings(_env_file=None, mcp_keepalive_seconds=0, public_url="https://example.org",  # type: ignore[call-arg]
                    **overrides)


def scripted_llm() -> FakeLlm:
    return FakeLlm([
        LlmTurn(assistant_content=[], text="", stop_reason="tool_use", usage=Usage(input_tokens=10),
                tool_calls=[ToolCall("t1", "search_addons", {"query": "kanji"})]),
        LlmTurn(assistant_content=[], text=f"Try **[Kanji Helper](/addon/{KANJI})**.", tool_calls=[],
                stop_reason="end_turn", usage=Usage(output_tokens=10), model="claude-haiku-5-5"),
    ])


@pytest.fixture
def make_client(server: MCPServer) -> Iterator[Any]:
    clients: list[TestClient] = []

    def make(llm: FakeLlm | None = None, **overrides: Any) -> TestClient:
        catalog = McpCatalog(server, timeout_seconds=10)
        client = TestClient(create_app(settings(**overrides), catalog=catalog, llm=llm or scripted_llm()))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


def sse_events(text: str) -> list[tuple[str, Any]]:
    events = []
    for chunk in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.mark.parametrize("path", ["/", "/search?q=kanji", f"/addon/{KANJI}", f"/addon/{OCCLUSION}?anki=25.02",
                                  "/top/rating", "/top/recently_updated", "/author/alice", "/stats", "/changes",
                                  "/about", "/tags", "/tag/dictionary", "/tag/obsolete"])
def test_pages_render(make_client: Any, path: str) -> None:
    response = make_client().get(path)
    assert response.status_code == 200, response.text
    assert "Anki Addons Catalog" in response.text
    assert '<span class="beta"' in response.text
    assert 'class="dataset-date"' in response.text and ">1 Sep 2026</a>" in response.text


def test_index_lists_top_addons(make_client: Any) -> None:
    assert f'href="/addon/{OCCLUSION}"' in make_client().get("/").text


def test_cards_show_votes_and_approval(make_client: Any) -> None:
    html = make_client().get("/").text
    assert "300 votes" in html and "98% approval" in html  # Image Occlusion Plus: 298 likes, 2 dislikes
    assert "<dt>Votes</dt><dd>300 (👍 298 · 👎 2)</dd>" in make_client().get(f"/addon/{OCCLUSION}").text


def test_addon_page_renders_readme_safely(make_client: Any) -> None:
    html = make_client().get(f"/addon/{KANJI}").text
    assert "<h1>Kanji Helper</h1>" in html
    assert "<script>alert(1)</script>" not in html
    assert 'href="https://x.org" target="_blank" rel="nofollow noopener noreferrer"' in html
    for hostile in ("alert(2)", "alert(3)", "javascript:", "<iframe", "evil.org", "display:none"):
        assert hostile not in html


def test_addon_page_renders_readme_raw_html(make_client: Any) -> None:
    html = make_client().get(f"/addon/{KANJI}").text
    assert ('<p align="center"><a href="https://y.org" target="_blank" rel="nofollow noopener noreferrer">'
            '<img src="https://github.com/alice/kanji-helper/raw/HEAD/img/b.png"></a></p>') in html


def test_addon_page_resolves_relative_readme_links_against_github(make_client: Any) -> None:
    html = make_client().get(f"/addon/{KANJI}").text
    assert 'href="https://github.com/alice/kanji-helper/blob/HEAD/docs/manual.md"' in html
    assert 'src="https://github.com/alice/kanji-helper/raw/HEAD/img/a.png"' in html
    assert 'href="#usage"' in html


def test_about_shows_dataset_date(make_client: Any) -> None:
    text = make_client().get("/about").text
    assert "collected on <b>1 Sep 2026</b>" in text
    assert "stored for 90 days" in text


def test_about_shows_contacts(make_client: Any) -> None:
    text = make_client().get("/about").text
    assert 'href="https://forums.ankiweb.net/t/anki-addons-dataset-a-detailed-list-of-addons/63090"' in text
    assert 'href="https://github.com/Aleks-Ya/anki-addons-catalog/issues"' in text


def test_compatibility_verdict(make_client: Any) -> None:
    assert "verdict-supported" in make_client().get(f"/addon/{KANJI}?anki=25.02").text


def test_header_has_no_dataset_date_when_catalog_is_down(make_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from anki_addons_catalog.application.catalog import CatalogService
    from anki_addons_catalog.domain.errors import CatalogUnavailable

    async def down(self: Any) -> None:
        raise CatalogUnavailable("down")
    monkeypatch.setattr(CatalogService, "latest_snapshot_info", down)
    response = make_client().get("/about")
    assert response.status_code == 200 and 'class="dataset-date"' not in response.text


def test_missing_addon_is_404(make_client: Any) -> None:
    assert make_client().get("/addon/42").status_code == 404


def test_unknown_top_metric_is_404(make_client: Any) -> None:
    assert make_client().get("/top/nope").status_code == 404


def test_history_json(make_client: Any) -> None:
    assert len(make_client().get(f"/addon/{OCCLUSION}/history").json()["points"]) == 2


def test_search_page_has_keyword_results_and_ai_section(make_client: Any) -> None:
    html = make_client().get("/search?q=kanji").text
    assert 'data-query="kanji"' in html
    assert f'href="/addon/{KANJI}"' in html


def test_search_filters_narrow_results_and_keep_in_links(make_client: Any) -> None:
    client = make_client()
    html = client.get("/search", params={"q": "image", "rating": "200", "tag": "image-occlusion"}).text
    assert f'href="/addon/{OCCLUSION}"' in html
    assert 'data-filters="tag=image-occlusion&amp;rating=200"' in html
    assert '<input type="hidden" name="tag" value="image-occlusion">' in html  # a new question keeps the filters
    assert 'href="/search?q=image&amp;rating=200"' in html  # the chip that removes the tag
    assert 'name="sort"' not in html  # a query ranks by relevance
    assert f'href="/addon/{KANJI}"' not in client.get("/search", params={"q": "kanji", "anki": "2.1.50"}).text


def test_search_without_query_browses_the_catalog(make_client: Any) -> None:
    client = make_client()
    html = client.get("/search").text
    assert "All addons <small>(2)</small>" in html and 'id="ai"' not in html and 'name="sort"' in html
    assert f'href="/addon/{HEATMAP}"' in client.get("/search", params={"obsolete": "1", "tag": "statistics"}).text
    assert client.get("/search", params={"tag": "nope", "q": "kanji"}).status_code == 200


def test_search_url_keeps_filters() -> None:
    assert search_url("a b", SearchFilters(tags=["cloze"], sort="likes"), 30) == "/search?q=a+b&tag=cloze&offset=30"
    assert search_url("", SearchFilters(sort="likes")) == "/search?sort=likes"
    assert search_url() == "/search"


def test_ask_applies_filters(make_client: Any) -> None:
    llm = scripted_llm()
    make_client(llm).get("/api/ask", params={"q": "kanji", "anki": "25.09", "tag": "dictionary"})
    assert "Visitor filters" in llm.requests[0][0]["content"]
    assert "Anki 25.09, dictionary" in llm.requests[0][0]["content"]


def test_tags_page_lists_categories(make_client: Any) -> None:
    html = make_client().get("/tags").text
    assert 'href="/tag/dictionary"' in html
    assert 'href="/tag/paid"' in html
    assert "Lookup, definitions, translation" in html


def test_tag_page_lists_addons_and_hides_obsolete_ones(make_client: Any) -> None:
    client = make_client()
    assert f'href="/addon/{KANJI}"' in client.get("/tag/dictionary").text
    statistics = client.get("/tag/statistics").text
    assert f'href="/addon/{HEATMAP}"' not in statistics
    assert "obsolete addons are hidden" in statistics
    assert f'href="/addon/{HEATMAP}"' in client.get("/tag/obsolete").text
    assert 'href="/search?tag=statistics"' in statistics


def test_unknown_tag_is_404(make_client: Any) -> None:
    assert make_client().get("/tag/nope").status_code == 404


def test_cards_and_addon_page_link_tags(make_client: Any) -> None:
    client = make_client()
    assert 'href="/tag/image-occlusion"' in client.get("/").text
    assert 'href="/tag/dictionary"' in client.get(f"/addon/{KANJI}").text


def test_static_links_are_root_relative(make_client: Any) -> None:
    # The custom-domain proxy reports http, so absolute links would be blocked as mixed content
    html = make_client().get("/").text
    assert 'href="/static/app.css?v=' in html
    assert "http://testserver/static" not in html


def test_stats_has_ai_tags(make_client: Any) -> None:
    html = make_client().get("/stats").text
    assert "AI tag" in html
    assert 'href="/tags"' in html


def test_sitemap_and_robots(make_client: Any) -> None:
    client = make_client()
    sitemap = client.get("/sitemap.xml").text
    assert f"<loc>https://example.org/addon/{KANJI}</loc>" in sitemap
    assert "<loc>https://example.org/tags</loc>" in sitemap
    assert "<loc>https://example.org/tag/dictionary</loc>" in sitemap
    robots = client.get("/robots.txt").text
    assert "Sitemap: https://example.org/sitemap.xml" in robots
    assert "Disallow: /admin/" in robots


def test_healthz(make_client: Any) -> None:
    assert make_client().get("/healthz").json()["status"] == "ok"


def test_ask_streams_answer(make_client: Any) -> None:
    response = make_client().get("/api/ask", params={"q": "kanji"})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.text)
    names = [name for name, _ in events]
    assert names[-3:] == ["answer", "addons", "done"]
    answer_html = events[-3][1]["html"]
    assert f'<strong><a href="/addon/{KANJI}">Kanji Helper</a></strong>' in answer_html
    assert events[-2][1]["count"] == 1 and "Kanji Helper" in events[-2][1]["html"]


def test_ask_validates_query(make_client: Any) -> None:
    client = make_client(max_query_chars=10)
    assert sse_events(client.get("/api/ask", params={"q": " "}).text)[0][0] == "error"
    assert sse_events(client.get("/api/ask", params={"q": "x" * 11}).text)[0][0] == "error"


def test_ask_rate_limited(make_client: Any) -> None:
    client = make_client(rate_limit_per_hour=1)
    client.get("/api/ask", params={"q": "kanji"})
    events = sse_events(client.get("/api/ask", params={"q": "kanji"}).text)
    assert events[0][0] == "error" and "many questions" in events[0][1]


def test_ask_budget_exhausted(make_client: Any) -> None:
    events = sse_events(make_client(daily_budget_usd=0).get("/api/ask", params={"q": "kanji"}).text)
    assert events[0][0] == "error" and "budget" in events[0][1]


def test_turnstile_gate(make_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client = make_client(turnstile_site_key="site", turnstile_secret="secret", session_secret="s")
    assert sse_events(client.get("/api/ask", params={"q": "kanji"}).text) == [("verify", None)]
    assert 'data-site-key="site"' in client.get("/search?q=kanji").text

    from anki_addons_catalog.interface.web import security

    async def fake_verify(self: Any, token: str, ip: str) -> bool:
        return token == "good"
    monkeypatch.setattr(security.HumanCheck, "verify", fake_verify)

    assert client.post("/api/verify", data={"token": "bad"}).status_code == 403
    response = client.post("/api/verify", data={"token": "good"})
    assert response.status_code == 200 and PASS_COOKIE in response.cookies
    events = sse_events(client.get("/api/ask", params={"q": "kanji"}).text)
    assert events[-1][0] == "done"

    client.cookies.set(PASS_COOKIE, "9999999999.forged")
    assert sse_events(client.get("/api/ask", params={"q": "kanji"}).text) == [("verify", None)]


def test_admin_usage_needs_a_configured_token(make_client: Any) -> None:
    assert make_client().get("/admin/usage", auth=("admin", "")).status_code == 404


def test_admin_usage_rejects_wrong_credentials(make_client: Any) -> None:
    client = make_client(admin_token="secret")
    response = client.get("/admin/usage")
    assert response.status_code == 401 and response.headers["www-authenticate"].startswith("Basic")
    assert client.get("/admin/usage", auth=("admin", "wrong")).status_code == 401


def test_admin_usage_counts_searches_and_views(make_client: Any) -> None:
    client = make_client(admin_token="secret")
    client.get("/search", params={"q": "kanji"})
    client.get("/search")
    client.get(f"/addon/{KANJI}")
    client.get("/api/ask", params={"q": "kanji"})
    html = client.get("/admin/usage", auth=("admin", "secret")).text
    assert '<small>Keyword searches</small><p class="kpi">1</p>' in html
    assert '<small>AI questions</small><p class="kpi">1</p>' in html
    assert '<small>Page views</small><p class="kpi">3</p>' in html
    assert '<tr><td>search</td><td class="num">2</td></tr>' in html
    assert '<meta name="robots" content="noindex">' in html


def test_admin_questions(make_client: Any) -> None:
    client = make_client(admin_token="secret")
    assert client.get("/admin/questions").status_code == 401
    assert client.get("/admin/questions.jsonl").status_code == 401
    client.get("/api/ask", params={"q": "kanji"})
    auth = ("admin", "secret")
    assert 'href="/admin/questions"' in client.get("/admin/usage", auth=auth).text
    html = client.get("/admin/questions", auth=auth).text
    assert '<a href="/admin/questions/1">kanji</a>' in html and "<td>answered</td><td>haiku-5-5</td>" in html
    detail = client.get("/admin/questions/1", auth=auth).text
    assert "· claude-haiku-5-5" in detail and "search_addons" in detail and f'<a href="/addon/{KANJI}">Kanji Helper</a>' in detail
    assert client.get("/admin/questions/2", auth=auth).status_code == 404
    export = client.get("/admin/questions.jsonl", auth=auth)
    assert export.headers["content-type"].startswith("application/x-ndjson")
    (row,) = [json.loads(line) for line in export.text.splitlines()]
    assert row["query"] == "kanji" and row["trace"][0]["tools"][0]["name"] == "search_addons"


def test_human_date() -> None:
    from anki_addons_catalog.interface.web.rendering import human_date
    assert human_date("2026-10-01") == "1 Oct 2026"
    assert human_date("2026-09-03T04:05:00+00:00") == "3 Sep 2026"
    assert human_date("soon") == "soon"
