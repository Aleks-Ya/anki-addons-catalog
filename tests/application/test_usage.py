from datetime import date
from pathlib import Path

from anki_addons_catalog.application.usage import AI_COST_USD, KEYWORD_SEARCH, UsageStats
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
