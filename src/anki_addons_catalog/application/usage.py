import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path

from anki_addons_catalog.application.limits import utc_today

log = logging.getLogger(__name__)

KEYWORD_SEARCH = "search.keyword"
AI_ASKED = "ai.asked"
AI_ANSWERED = "ai.answered"
AI_CACHED = "ai.cached"
AI_FAILED = "ai.failed"
AI_REFUSED = "ai.refused"
AI_RATE_LIMITED = "ai.rate_limited"
AI_VERIFY = "ai.verify"
AI_BUDGET_EXHAUSTED = "ai.budget_exhausted"
AI_COST_USD = "ai.cost_usd"
VIEW_PREFIX = "view."

MEMORY = ":memory:"


class UsageStats:
    """Daily usage counters in SQLite (UTC days); ":memory:" keeps them only until restart.

    With a `backup` file the database lives in memory, is restored from the file on start and is written back as a
    whole by `save()`. This suits an HF Storage Bucket mounted as a volume: such a mount cannot update a file in place,
    as SQLite does, but it can replace a whole file.

    A failed write is logged and ignored: statistics never break a page."""

    def __init__(self, path: str = MEMORY, today: Callable[[], date] = utc_today, backup: str | None = None) -> None:
        self.path = path
        self.backup = backup
        self._today = today
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        if backup:
            self._restore(Path(backup))
        self._db.execute("CREATE TABLE IF NOT EXISTS counters (day TEXT NOT NULL, name TEXT NOT NULL, "
                         "value REAL NOT NULL, PRIMARY KEY (day, name))")
        self._saved_changes = self._db.total_changes
        self._save_lock = threading.Lock()

    def _restore(self, backup: Path) -> None:
        if not backup.exists():
            return
        try:
            self._db.deserialize(backup.read_bytes())
            if self._db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("integrity check failed")
            log.info("Usage statistics restored from %s", backup)
        except (OSError, sqlite3.Error):
            log.warning("Cannot restore usage statistics from %s, starting empty", backup, exc_info=True)
            self._db.close()
            self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)

    @property
    def persistent(self) -> bool:
        return self.path != MEMORY or self.backup is not None

    def save(self) -> None:
        """Writes the whole database to the backup file if anything changed since the last save."""
        with self._save_lock:  # the periodic save runs in a worker thread
            if not self.backup or self._db.total_changes == self._saved_changes:
                return
            changes = self._db.total_changes
            try:
                Path(self.backup).write_bytes(self._db.serialize())
                self._saved_changes = changes
            except (OSError, sqlite3.Error):
                log.warning("Cannot save usage statistics to %s", self.backup, exc_info=True)

    def add(self, name: str, amount: float = 1.0) -> None:
        try:
            self._db.execute("INSERT INTO counters (day, name, value) VALUES (?, ?, ?) "
                             "ON CONFLICT (day, name) DO UPDATE SET value = value + excluded.value",
                             (self._today().isoformat(), name, amount))
        except sqlite3.Error:
            log.warning("Cannot record usage %s", name, exc_info=True)

    def today(self, name: str) -> float:
        row = self._db.execute("SELECT value FROM counters WHERE day = ? AND name = ?",
                               (self._today().isoformat(), name)).fetchone()
        return float(row[0]) if row else 0.0

    def daily(self, days: int = 30) -> list[tuple[str, dict[str, float]]]:
        """Counters of the last `days` days that have any, newest first."""
        result: dict[str, dict[str, float]] = {}
        rows = self._db.execute("SELECT day, name, value FROM counters WHERE day IN "
                                "(SELECT DISTINCT day FROM counters ORDER BY day DESC LIMIT ?) ORDER BY day DESC",
                                (days,))
        for day, name, value in rows:
            result.setdefault(day, {})[name] = value
        return list(result.items())

    def totals(self) -> dict[str, float]:
        return dict(self._db.execute("SELECT name, SUM(value) FROM counters GROUP BY name").fetchall())

    def first_day(self) -> str | None:
        row = self._db.execute("SELECT MIN(day) FROM counters").fetchone()
        return row[0] if row else None

    def close(self) -> None:
        self.save()
        self._db.close()
