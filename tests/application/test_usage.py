from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from anki_addons_catalog.application.usage import AI_COST_USD, KEYWORD_SEARCH, QuestionRecord, UsageStats
from anki_addons_catalog.bootstrap import create_usage
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


def test_backup_survives_restart(tmp_path: Path) -> None:
    backup = tmp_path / "usage.sqlite3"
    usage = UsageStats(backup=str(backup))
    assert usage.persistent and not backup.exists()
    usage.add(KEYWORD_SEARCH)
    usage.save()
    usage.add(KEYWORD_SEARCH)
    usage.close()
    restored = UsageStats(backup=str(backup))
    assert restored.path == ":memory:" and restored.today(KEYWORD_SEARCH) == 2


def test_save_writes_only_changes(tmp_path: Path) -> None:
    backup = tmp_path / "usage.sqlite3"
    usage = UsageStats(backup=str(backup))
    usage.save()
    assert not backup.exists()
    usage.add(KEYWORD_SEARCH)
    usage.save()
    backup.write_bytes(b"replaced")
    usage.save()
    assert backup.read_bytes() == b"replaced"


def test_damaged_backup_starts_empty(tmp_path: Path) -> None:
    backup = tmp_path / "usage.sqlite3"
    backup.write_bytes(b"not a database" * 100)
    usage = UsageStats(backup=str(backup))
    assert usage.first_day() is None
    usage.add(KEYWORD_SEARCH)
    usage.close()
    assert UsageStats(backup=str(backup)).today(KEYWORD_SEARCH) == 1


def test_create_usage_prefers_setting_then_mounted_volume(tmp_path: Path) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    mounted = create_usage(settings, storage=tmp_path)
    assert mounted.path == ":memory:" and mounted.backup == str(tmp_path / "usage.sqlite3")
    assert not create_usage(settings, storage=tmp_path / "missing").persistent
    file_db = str(tmp_path / "x.db")
    explicit = create_usage(Settings(_env_file=None, usage_db=file_db), storage=tmp_path)  # type: ignore[call-arg]
    assert explicit.path == file_db and explicit.backup is None


def test_questions_round_trip() -> None:
    usage = UsageStats(now=lambda: datetime(2026, 10, 1, 12, 30, tzinfo=UTC))
    trace = [{"stop": "tool_use", "tools": [{"name": "search_addons", "arguments": {"query": "kanji"}}]},
             {"stop": "end_turn", "tools": []}]
    usage.record_question(QuestionRecord("kanji", "2026-09-01", "answered", rounds=2, cost_usd=0.03,
                                         answer="Use it.", addon_ids=[1, 2], trace=trace))
    usage.record_question(QuestionRecord("other", outcome="cached"))
    assert usage.question_count() == 2
    newest, oldest = usage.questions()
    assert (newest["query"], oldest["query"]) == ("other", "kanji")
    assert oldest["tool_calls"] == 1 and oldest["asked_at"] == "2026-10-01T12:30:00+00:00"
    assert "answer" not in oldest
    full = usage.question(oldest["id"])
    assert full is not None and full["trace"] == trace and full["addon_ids"] == [1, 2] and full["answer"] == "Use it."
    assert usage.question(999) is None
    assert [q["query"] for q in usage.iter_questions()] == ["kanji", "other"]


def test_old_questions_are_pruned_on_save(tmp_path: Path) -> None:
    now = [datetime(2026, 10, 1, tzinfo=UTC)]
    usage = UsageStats(backup=str(tmp_path / "usage.sqlite3"), question_days=90, now=lambda: now[0])
    usage.record_question(QuestionRecord("old"))
    now[0] += timedelta(days=60)
    usage.record_question(QuestionRecord("new"))
    now[0] += timedelta(days=31)
    usage.close()
    restored = UsageStats(backup=str(tmp_path / "usage.sqlite3"), now=lambda: now[0])
    assert [q["query"] for q in restored.iter_questions()] == ["new"]
