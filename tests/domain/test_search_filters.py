from datetime import date

from starlette.datastructures import QueryParams

from anki_addons_catalog.domain.models import MAX_KEYWORD_CHARS, MAX_LANGUAGES, SearchFilters


def parse(query: str) -> SearchFilters:
    return SearchFilters.parse(QueryParams(query))


def test_empty_url_hides_obsolete_only() -> None:
    filters = parse("")
    assert filters == SearchFilters()
    assert filters.params() == [] and filters.chips() == []
    assert filters.tool_args(date(2026, 10, 1)) == {"exclude_tags": ["obsolete"]}


def test_parse_and_params_round_trip() -> None:
    query = "anki=25.09&tag=statistics&tag=cloze&lang=Python&lang=C%2B%2B&obsolete=1&nopaid=1&nofork=1&recent=1&active=1&github=1&rating=50&kw=image+occlusion&sort=likes"
    filters = parse(query)
    assert QueryParams(filters.params()) == QueryParams(query)
    assert filters.tool_args(date(2026, 10, 1)) == {
        "compatible_with_anki": "25.09", "tags": ["statistics", "cloze"], "language": ["Python", "C++"],
        "exclude_tags": ["paid"], "is_fork": False,
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


def test_browsing_only_filters_are_left_out_on_request() -> None:
    assert parse("sort=stars&kw=heatmap&tag=cloze").params(browse=False) == [("tag", "cloze")]


def test_keywords_are_trimmed_and_capped() -> None:
    assert parse("kw=%20image%20%20%0Aocclusion%20").keywords == "image occlusion"
    assert parse("kw=%20%20").keywords is None
    assert len(parse("kw=" + "a" * (MAX_KEYWORD_CHARS + 5)).keywords or "") == MAX_KEYWORD_CHARS


def test_keywords_chip_comes_first_and_removes_the_keywords() -> None:
    filters = parse("tag=cloze&kw=heatmap")
    chips = dict(filters.chips())
    assert list(chips) == ["Keywords: heatmap", "cloze"]
    assert chips["Keywords: heatmap"] == SearchFilters(tags=["cloze"])


def test_hide_forks_chip() -> None:
    filters = parse("nofork=1")
    assert filters.hide_forks and [label for label, _ in filters.chips()] == ["No forks"]


def test_languages_keep_the_first_spelling_and_drop_invalid_values() -> None:
    filters = parse("lang=python&lang=Common%20Lisp&lang=Python&lang=%3Cb%3E&lang=")
    assert filters.languages == ["python", "Common Lisp"]


def test_languages_are_capped() -> None:
    assert len(parse("&".join(f"lang=L{i}" for i in range(MAX_LANGUAGES + 5))).languages) == MAX_LANGUAGES


def test_language_chips_remove_one_language_each() -> None:
    filters = parse("lang=Python&lang=JavaScript")
    chips = dict(filters.chips())
    assert list(chips) == ["Language: Python", "Language: JavaScript"]
    assert chips["Language: Python"].languages == ["JavaScript"]
    assert filters.describe() == "obsolete hidden, Language: Python, Language: JavaScript"
