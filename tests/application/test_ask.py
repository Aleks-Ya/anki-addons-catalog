from datetime import date
from typing import Any

import pytest

from anki_addons_catalog.adapters.mcp.catalog import McpCatalog
from anki_addons_catalog.application import usage as u
from anki_addons_catalog.application.ask import (
    FINAL_ROUND_NOTE,
    AskService,
    BudgetExhausted,
    _tool_status,
    extract_cards,
    normalize_query,
    referenced_ids,
    with_filters,
)
from anki_addons_catalog.application.limits import DailyBudget, Pricing
from anki_addons_catalog.application.usage import UsageStats
from anki_addons_catalog.config import Settings
from anki_addons_catalog.domain.models import AddonCard, AnswerEvent, LlmTurn, SearchFilters, ToolCall, Usage
from tests.conftest import FakeLlm
from tests.fixtures import KANJI, OCCLUSION

pytestmark = pytest.mark.anyio

PRICING = Pricing(2, 10, 0.2, 2.5)
TOOLS = ["search_addons", "get_addon", "check_compatibility"]


def answer(text: str) -> LlmTurn:
    return LlmTurn(assistant_content=[{"type": "text", "text": text}], text=text, tool_calls=[],
                   stop_reason="end_turn", usage=Usage(input_tokens=1000, output_tokens=200), model="claude-haiku-5-5")


def tools(*calls: ToolCall) -> LlmTurn:
    content = [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments} for c in calls]
    return LlmTurn(assistant_content=content, text="", tool_calls=list(calls), stop_reason="tool_use",
                   usage=Usage(input_tokens=1000, output_tokens=50))


def service(catalog: McpCatalog, llm: FakeLlm, budget_usd: float = 1.0, max_rounds: int = 3,
            usage: UsageStats | None = None) -> AskService:
    async def snapshot() -> str:
        return "2026-09-01"
    return AskService(catalog, llm, DailyBudget(budget_usd, PRICING, today=lambda: date(2026, 10, 1)),
                      allowed_tools=TOOLS, max_tool_rounds=max_rounds, snapshot=snapshot, usage=usage)


async def collect(ask: AskService, query: str, filters: SearchFilters | None = None) -> list[AnswerEvent]:
    return [event async for event in ask.ask(query, filters)]


async def test_offers_every_configured_tool_including_list_tags(catalog: McpCatalog) -> None:
    configured = Settings.model_fields["ai_tools"].default
    ask = AskService(catalog, FakeLlm([]), DailyBudget(1.0, PRICING), allowed_tools=configured)
    names = [t.name for t in await ask.tools()]
    assert sorted(names) == sorted(configured)
    assert "list_tags" in names


async def test_answers_with_tool_calls_and_cards(catalog: McpCatalog) -> None:
    llm = FakeLlm([
        tools(ToolCall("t1", "search_addons", {"query": "kanji"}),
              ToolCall("t2", "check_compatibility", {"addon_ids": [KANJI], "anki_version": "25.02"})),
        answer(f"Use [Kanji Helper](/addon/{KANJI})."),
    ])
    events = await collect(service(catalog, llm), "  kanji   for 25.02 ")

    types = [e.type for e in events]
    assert types[-3:] == ["answer", "addons", "done"]
    assert "Searching for “kanji”" in [e.data for e in events if e.type == "status"]
    assert "".join(e.data for e in events if e.type == "text") == f"Use [Kanji Helper](/addon/{KANJI})."
    cards = next(e.data for e in events if e.type == "addons")
    assert [c["id"] for c in cards] == [KANJI]

    assert {t.name for t in llm.tools} == set(TOOLS)
    assert llm.requests[0][0]["content"] == "(Dataset snapshot: 2026-09-01.)\n\nSearch query: kanji for 25.02"
    results = llm.requests[1][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert all(not r["is_error"] for r in results)


async def test_records_the_question_trace(catalog: McpCatalog) -> None:
    llm = FakeLlm([tools(ToolCall("t1", "search_addons", {"query": "kanji"})),
                   answer(f"Use [Kanji Helper](/addon/{KANJI}).")])
    usage = UsageStats()
    await collect(service(catalog, llm, usage=usage), " kanji ")
    (q,) = usage.iter_questions()
    assert (q["query"], q["snapshot"], q["outcome"], q["rounds"]) == ("kanji", "2026-09-01", "answered", 2)
    assert (q["input_tokens"], q["output_tokens"]) == (2000, 250)
    assert q["cost_usd"] == pytest.approx(usage.today(u.AI_COST_USD))
    assert q["answer"] == f"Use [Kanji Helper](/addon/{KANJI})." and q["addon_ids"] == [KANJI]
    first, last = q["trace"]
    assert first["stop"] == "tool_use" and last["stop"] == "end_turn" and last["tools"] == []
    (call,) = first["tools"]
    assert call["name"] == "search_addons" and call["arguments"] == {"query": "kanji"}
    assert not call["is_error"] and call["result_chars"] > 0
    assert q["error"] is None and q["duration_ms"] >= 0
    assert q["model"] == "claude-haiku-5-5"


async def test_records_failures_and_refusals(catalog: McpCatalog) -> None:
    class Broken(FakeLlm):
        async def turn(self, *args: Any) -> LlmTurn:
            raise RuntimeError("boom")

    usage = UsageStats()
    await collect(service(catalog, Broken([]), usage=usage), "a")
    refusal = LlmTurn(assistant_content=[], text="", tool_calls=[], stop_reason="refusal")
    await collect(service(catalog, FakeLlm([refusal]), usage=usage), "b")
    failed, refused = usage.iter_questions()
    assert failed["outcome"] == "failed" and "boom" in failed["error"]
    assert refused["outcome"] == "refused" and refused["rounds"] == 1


async def test_answers_are_cached(catalog: McpCatalog) -> None:
    llm = FakeLlm([answer("Nothing fits.")])
    usage = UsageStats()
    ask = service(catalog, llm, usage=usage)
    first = await collect(ask, "Kanji")
    second = await collect(ask, "kanji")
    assert [e.type for e in second] == ["answer", "addons", "done"]
    assert second == first[-3:]
    assert len(llm.requests) == 1
    assert [usage.today(n) for n in (u.AI_ASKED, u.AI_ANSWERED, u.AI_CACHED)] == [2, 1, 1]
    assert usage.today(u.AI_COST_USD) == PRICING.cost(Usage(input_tokens=1000, output_tokens=200))
    assert [(q["outcome"], q["answer"], q["cost_usd"]) for q in usage.iter_questions()][1] == ("cached", "Nothing fits.", 0)


async def test_budget_exhausted(catalog: McpCatalog) -> None:
    usage = UsageStats()
    ask = service(catalog, FakeLlm([answer("a")]), budget_usd=0, usage=usage)
    with pytest.raises(BudgetExhausted):
        await collect(ask, "kanji")
    assert usage.today(u.AI_BUDGET_EXHAUSTED) == 1
    assert [q["outcome"] for q in usage.iter_questions()] == ["budget"]


async def test_refusal(catalog: McpCatalog) -> None:
    refusal = LlmTurn(assistant_content=[], text="", tool_calls=[], stop_reason="refusal")
    usage = UsageStats()
    events = await collect(service(catalog, FakeLlm([refusal]), usage=usage), "bad")
    assert [e.type for e in events] == ["status", "error"]
    assert usage.today(u.AI_REFUSED) == 1


async def test_last_round_asks_for_the_answer(catalog: McpCatalog) -> None:
    call = ToolCall("t", "search_addons", {"query": "x"})
    llm = FakeLlm([tools(call), tools(call), answer("Final.")])
    events = await collect(service(catalog, llm, max_rounds=2), "q")
    assert events[-3].data == "Final."
    assert llm.requests[2][-1]["content"][-1] == {"type": "text", "text": FINAL_ROUND_NOTE}


async def test_stops_after_max_rounds_even_if_model_keeps_calling(catalog: McpCatalog) -> None:
    call = ToolCall("t", "search_addons", {"query": "x"})
    first = tools(call)
    first.text = "Partial answer."
    llm = FakeLlm([first, tools(call)])
    events = await collect(service(catalog, llm, max_rounds=1), "q")
    assert [e.data for e in events if e.type == "answer"] == ["Partial answer."]
    assert len(llm.requests) == 2


async def test_unknown_tool_and_tool_errors_are_reported_to_the_model(catalog: McpCatalog) -> None:
    llm = FakeLlm([tools(ToolCall("t1", "query_sql", {"sql_query": "SELECT 1"}),
                         ToolCall("t2", "get_addon", {"addon_id": 42})), answer("Sorry.")])
    await collect(service(catalog, llm), "q")
    results = llm.requests[1][-1]["content"]
    assert [r["is_error"] for r in results] == [True, True]


async def test_empty_answer_is_an_error(catalog: McpCatalog) -> None:
    events = await collect(service(catalog, FakeLlm([answer("")])), "q")
    assert events[-1].type == "error"


def test_extract_cards_from_tool_results() -> None:
    cards: dict[int, AddonCard] = {}
    page = {"items": [{"id": 1, "title": "A", "url": "u", "rating": 1}], "total": 1}
    similar = [{"card": {"id": 2, "title": "B", "url": "u"}, "score": 0.5, "reasons": []}]
    details: dict[str, Any] = {"id": 3, "anki_web": {"title": "C", "addon_page_url": "u"}, "github": None}
    extract_cards(page, cards)
    extract_cards(similar, cards)
    extract_cards(details, cards)
    assert sorted(cards) == [1, 2, 3]
    assert cards[3].title == "C"


def test_extract_cards_keeps_ai_tags() -> None:
    cards: dict[int, AddonCard] = {}
    page = {"items": [{"id": 1, "title": "A", "url": "u", "ai_tags": ["statistics"]}], "total": 1}
    details = {"id": 2, "anki_web": {"title": "B", "addon_page_url": "u"}, "ai": {"tags": ["cloze", "beta"]}}
    extract_cards([page, details], cards)
    assert cards[1].ai_tags == ["statistics"]
    assert cards[2].ai_tags == ["cloze", "beta"]


def test_extract_cards_keeps_fork_relations() -> None:
    cards: dict[int, AddonCard] = {}
    page = {"items": [{"id": 1, "title": "A", "url": "u", "forks": [2]}], "total": 1}
    details = {"id": 2, "anki_web": {"title": "B", "addon_page_url": "u"},
               "forked_from": {"id": 1, "evidence": "ai"}, "forks": []}
    extract_cards([page, details], cards)
    assert cards[1].forks == [2] and cards[1].forked_from is None
    assert cards[2].forked_from == 1 and cards[2].forks == []


def test_extract_cards_prefers_full_cards_to_fork_family_members() -> None:
    cards: dict[int, AddonCard] = {}
    family = {"members": [{"id": 1, "title": "A", "url": "u", "role": "original", "compatibility": "likely"}]}
    page = {"items": [{"id": 1, "title": "A", "url": "u", "ai_summary": "Does A."}], "total": 1}
    extract_cards([family, page, family], cards)
    assert cards[1].ai_summary == "Does A."


def test_referenced_ids_in_order_without_duplicates() -> None:
    text = f"[B](/addon/{OCCLUSION}) and [A](https://ankiweb.net/shared/info/{KANJI}) and [B](/addon/{OCCLUSION})"
    assert referenced_ids(text) == [OCCLUSION, KANJI]


def test_normalize_query() -> None:
    assert normalize_query("  a \n b  ") == "a b"


async def test_visitor_filters_narrow_the_model_searches(catalog: McpCatalog) -> None:
    llm = FakeLlm([tools(ToolCall("t1", "search_addons", {"query": "a", "exclude_tags": ["paid"]}),
                         ToolCall("t2", "get_addon", {"addon_id": KANJI})),
                   answer("Done.")])
    usage = UsageStats()
    filters = SearchFilters(anki="25.02", min_rating=200)
    await collect(service(catalog, llm, usage=usage), "image", filters)
    assert llm.requests[0][0]["content"] == (
        "(Dataset snapshot: 2026-09-01.)\n\n(Visitor filters, applied to every search_addons and filter_addons "
        "call: obsolete hidden, Anki 25.02, ≥ 200 votes.)\n\nSearch query: image")
    search, details = llm.requests[1][-1]["content"]
    assert '"total":0' in search["content"].replace(" ", "")  # Kanji Helper is rated 120
    assert not details["is_error"]
    (q,) = usage.iter_questions()
    assert q["filters"] == "anki=25.02&rating=200"


async def test_answers_are_cached_per_filters(catalog: McpCatalog) -> None:
    llm = FakeLlm([answer("One."), answer("Two.")])
    ask = service(catalog, llm)
    await collect(ask, "kanji")
    await collect(ask, "kanji", SearchFilters(hide_paid=True))
    await collect(ask, "kanji", SearchFilters(hide_paid=True))
    assert len(llm.requests) == 2


def test_with_filters_joins_tags_and_overrides_the_rest() -> None:
    model = {"query": "x", "tags": ["cloze"], "exclude_tags": ["obsolete"], "min_rating": 5}
    visitor = {"tags": ["statistics"], "exclude_tags": ["obsolete", "paid"], "min_rating": 50}
    assert with_filters(model, visitor) == {"query": "x", "tags": ["cloze", "statistics"],
                                            "exclude_tags": ["obsolete", "paid"], "min_rating": 50}


def test_with_filters_keeps_forks_the_model_asks_for() -> None:
    assert with_filters({"fork_of": 7}, {"is_fork": False, "min_rating": 50}) == {"fork_of": 7, "min_rating": 50}
    assert with_filters({"query": "x"}, {"is_fork": False}) == {"query": "x", "is_fork": False}


def test_tool_status_for_forks() -> None:
    assert _tool_status(ToolCall("t", "filter_addons", {"fork_of": 7})) == "Looking for forks of addon 7"
    assert _tool_status(ToolCall("t", "filter_addons", {"tags": ["cloze"]})) == "Filtering the catalog"
    assert _tool_status(ToolCall("t", "compare_forks", {"addon_id": 7})) == "Comparing versions of addon 7"
