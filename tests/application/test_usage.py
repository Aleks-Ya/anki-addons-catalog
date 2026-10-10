from datetime import date
from pathlib import Path

from anki_addons_catalog.application.usage import AI_COST_USD, KEYWORD_SEARCH, UsageStats
from anki_addons_catalog.bootstrap import usage_db_path
from anki_addons_catalog.config import Settings


def test_counts_per_day() -> None:
    day = [date(2026, 10, 1)]
    usage = UsageStats(today=lambda: day[0])
    assert not usage.persistent and usage.first_day() is None
    usage.add(KEYWORD_SEARCH)
    usage.add(KEYWORD_SEARCH)
    usage.add(AI_COST_USD, 0.25)
    day[0] = date(2026, 10, 2)
    usage.add(KEYWORD_SEARCH)

    assert usage.today(KEYWORD_SEARCH) == 1
    assert usage.today(AI_COST_USD) == 0
    assert usage.daily() == [("2026-10-02", {KEYWORD_SEARCH: 1}),
                             ("2026-10-01", {KEYWORD_SEARCH: 2, AI_COST_USD: 0.25})]
    assert usage.daily(days=1) == [("2026-10-02", {KEYWORD_SEARCH: 1})]
    assert usage.totals() == {KEYWORD_SEARCH: 3, AI_COST_USD: 0.25}
    assert usage.first_day() == "2026-10-01"


def test_file_database_survives_reopening(tmp_path: Path) -> None:
    path = str(tmp_path / "usage.sqlite3")
    usage = UsageStats(path)
    usage.add(KEYWORD_SEARCH)
    usage.close()
    reopened = UsageStats(path)
    assert reopened.persistent
    assert reopened.today(KEYWORD_SEARCH) == 1


def test_db_path_prefers_setting_then_persistent_storage(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert usage_db_path(settings, storage=tmp_path) == str(tmp_path / "usage.sqlite3")
    assert usage_db_path(settings, storage=tmp_path / "missing") == ":memory:"
    assert usage_db_path(Settings(_env_file=None, usage_db="x.db"), storage=tmp_path) == "x.db"  # type: ignore[call-arg]
