from datetime import date

from starlette.datastructures import QueryParams

from anki_addons_catalog.domain.models import SearchFilters


def parse(query: str) -> SearchFilters:
    return SearchFilters.parse(QueryParams(query))


def test_empty_url_hides_obsolete_only() -> None:
    filters = parse("")
    assert filters == SearchFilters()
    assert filters.params() == [] and filters.chips() == []
    assert filters.tool_args(date(2026, 10, 1)) == {"exclude_tags": ["obsolete"]}


def test_parse_and_params_round_trip() -> None:
    query = "anki=25.09&tag=statistics&tag=cloze&obsolete=1&nopaid=1&nofork=1&recent=1&active=1&github=1&rating=50&sort=likes"
    filters = parse(query)
    assert QueryParams(filters.params()) == QueryParams(query)
    assert filters.tool_args(date(2026, 10, 1)) == {
        "compatible_with_anki": "25.09", "tags": ["statistics", "cloze"], "exclude_tags": ["paid"], "is_fork": False,
        "updated_after": "2024-10-01", "archived": False, "has_github": True, "min_rating": 50}


def test_invalid_values_are_dropped() -> None:
    filters = parse("anki=latest&tag=Statistics&tag=statistics&tag=a%20b&rating=7&sort=title&obsolete=yes")
    assert filters == SearchFilters(tags=["statistics"])


def test_chips_remove_one_filter_each() -> None:
    filters = parse("anki=2.1.66&tag=cloze&recent=1&rating=10")
    chips = dict(filters.chips())
    assert list(chips) == ["Anki 2.1.66", "cloze", "Updated in 2 years", "≥ 10 votes"]
    assert chips["cloze"].tags == [] and chips["cloze"].anki == "2.1.66"
    assert filters.describe() == "obsolete hidden, Anki 2.1.66, cloze, Updated in 2 years, ≥ 10 votes"


def test_sort_is_left_out_on_request() -> None:
    assert parse("sort=stars&tag=cloze").params(sort=False) == [("tag", "cloze")]


def test_hide_forks_chip() -> None:
    filters = parse("nofork=1")
    assert filters.hide_forks and [label for label, _ in filters.chips()] == ["No forks"]
