import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

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

_QUESTION_COLUMNS = ("asked_at", "query", "snapshot", "outcome", "rounds", "input_tokens", "output_tokens",
                     "cache_read_tokens", "cache_write_tokens", "cost_usd", "duration_ms", "answer", "addon_ids",
                     "trace", "error", "model")
_JSON_COLUMNS = ("addon_ids", "trace")


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class QuestionRecord:
    """One AI question: what was asked, how it ended, what it cost, and a trace of the model rounds and tool calls.

    `outcome` is one of answered, cached, failed, refused, budget, unavailable, cancelled (the visitor left)."""
    query: str
    snapshot: str | None = None
    outcome: str = "cancelled"
    asked_at: str = ""
    rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    answer: str | None = None
    addon_ids: list[int] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    model: str | None = None


class UsageStats:
    """Daily usage counters in SQLite (UTC days); ":memory:" keeps them only until restart.

    With a `backup` file the database lives in memory, is restored from the file on start and is written back as a
    whole by `save()`. This suits an HF Storage Bucket mounted as a volume: such a mount cannot update a file in place,
    as SQLite does, but it can replace a whole file.

    The `questions` table logs every AI question (without the visitor's IP) for `question_days` days.

    A failed write is logged and ignored: statistics never break a page."""

    def __init__(self, path: str = MEMORY, today: Callable[[], date] = utc_today, backup: str | None = None,
                 question_days: int = 90, now: Callable[[], datetime] = utc_now) -> None:
        self.path = path
        self.backup = backup
        self.question_days = question_days
        self._today = today
        self._now = now
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        if backup:
            self._restore(Path(backup))
        self._db.execute("CREATE TABLE IF NOT EXISTS counters (day TEXT NOT NULL, name TEXT NOT NULL, "
                         "value REAL NOT NULL, PRIMARY KEY (day, name))")
        self._db.execute("CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, asked_at TEXT NOT NULL, "
                         "query TEXT NOT NULL, snapshot TEXT, outcome TEXT NOT NULL, rounds INTEGER, "
                         "input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, "
                         "cache_write_tokens INTEGER, cost_usd REAL, duration_ms INTEGER, answer TEXT, "
                         "addon_ids TEXT, trace TEXT, error TEXT, model TEXT)")
        self._db.execute("CREATE INDEX IF NOT EXISTS questions_asked_at ON questions (asked_at)")
        if "model" not in {row[1] for row in self._db.execute("PRAGMA table_info(questions)")}:
            self._db.execute("ALTER TABLE questions ADD COLUMN model TEXT")  # a backup from before the column
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
            self.prune_questions()
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

    def record_question(self, record: QuestionRecord) -> None:
        row = asdict(record)
        row["asked_at"] = record.asked_at or self._now().isoformat(timespec="seconds")
        for name in _JSON_COLUMNS:
            row[name] = json.dumps(row[name], ensure_ascii=False)
        try:
            self._db.execute(f"INSERT INTO questions ({', '.join(_QUESTION_COLUMNS)}) "
                             f"VALUES ({', '.join('?' * len(_QUESTION_COLUMNS))})",
                             [row[name] for name in _QUESTION_COLUMNS])
        except sqlite3.Error:
            log.warning("Cannot record the question", exc_info=True)

    def questions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        """Questions newest first, without the answer and the trace (but with the number of tool calls)."""
        rows = self._db.execute(
            "SELECT id, asked_at, query, outcome, rounds, input_tokens, output_tokens, cost_usd, duration_ms, model, "
            "(SELECT COUNT(*) FROM json_each(trace) AS r, json_each(r.value, '$.tools')) AS tool_calls "
            "FROM questions ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        return [self._as_dict(rows, row) for row in rows.fetchall()]

    def question_count(self) -> int:
        return int(self._db.execute("SELECT COUNT(*) FROM questions").fetchone()[0])

    def question(self, question_id: int) -> dict[str, Any] | None:
        rows = self._db.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
        row = rows.fetchone()
        return self._as_dict(rows, row) if row else None

    def iter_questions(self) -> Iterator[dict[str, Any]]:
        """All questions with every field, oldest first."""
        rows = self._db.execute("SELECT * FROM questions ORDER BY id")
        for row in rows.fetchall():
            yield self._as_dict(rows, row)

    def prune_questions(self) -> None:
        cutoff = (self._now() - timedelta(days=self.question_days)).isoformat(timespec="seconds")
        try:
            self._db.execute("DELETE FROM questions WHERE asked_at < ?", (cutoff,))
        except sqlite3.Error:
            log.warning("Cannot prune old questions", exc_info=True)

    @staticmethod
    def _as_dict(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
        result = {column[0]: value for column, value in zip(cursor.description, row, strict=True)}
        for name in _JSON_COLUMNS:
            if isinstance(result.get(name), str):
                result[name] = json.loads(result[name])
        return result

    def close(self) -> None:
        self.save()
        self._db.close()
