import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from anki_addons_catalog.domain.models import Usage

Clock = Callable[[], float]


class TtlCache[K, V]:
    """In-memory cache with a fixed time-to-live and a size cap (oldest entries evicted first)."""

    def __init__(self, ttl_seconds: float, max_entries: int = 1000, clock: Clock = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._data: dict[K, tuple[float, V]] = {}

    def get(self, key: K) -> V | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < self._clock():
            del self._data[key]
            return None
        return value

    def put(self, key: K, value: V) -> None:
        if self._ttl <= 0:
            return
        self._data.pop(key, None)
        while len(self._data) >= self._max:
            del self._data[next(iter(self._data))]
        self._data[key] = (self._clock() + self._ttl, value)


class RateLimiter:
    """Token bucket per client key: `per_hour` requests, refilled continuously."""

    def __init__(self, per_hour: int, clock: Clock = time.monotonic, max_keys: int = 10000) -> None:
        self._capacity = float(per_hour)
        self._rate = per_hour / 3600.0
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}

    def allow(self, key: str) -> bool:
        if self._capacity <= 0:
            return True
        now = self._clock()
        tokens, last = self._buckets.pop(key, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - last) * self._rate)
        allowed = tokens >= 1.0
        if allowed:
            tokens -= 1.0
        if len(self._buckets) >= self._max_keys:
            del self._buckets[next(iter(self._buckets))]
        self._buckets[key] = (tokens, now)
        return allowed


@dataclass(frozen=True)
class Pricing:
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float
    long: "Pricing | None" = None  # prices for a prompt over `long_above_tokens` (Haiku 5.5)
    long_above_tokens: int = 100_000

    def cost(self, usage: Usage) -> float:
        prompt = usage.input_tokens + usage.cache_read_input_tokens + usage.cache_creation_input_tokens
        if self.long and prompt > self.long_above_tokens:
            return self.long.cost(usage)
        return (usage.input_tokens * self.input_per_mtok
                + usage.output_tokens * self.output_per_mtok
                + usage.cache_read_input_tokens * self.cache_read_per_mtok
                + usage.cache_creation_input_tokens * self.cache_write_per_mtok) / 1_000_000


def utc_today() -> date:
    return datetime.now(UTC).date()


def utc_now() -> datetime:
    return datetime.now(UTC)


class Budget:
    """Global AI spend caps in USD per UTC day and per UTC month; a negative limit turns a cap off.

    `pause_until()` also stops the AI search until a given time, e.g. when the API reports the workspace spend limit."""

    def __init__(self, daily_usd: float, monthly_usd: float, pricing: Pricing, today: Callable[[], date] = utc_today,
                 now: Callable[[], datetime] = utc_now, spent_today: float = 0.0,
                 spent_this_month: float = 0.0) -> None:
        self._daily = daily_usd
        self._monthly = monthly_usd
        self._pricing = pricing
        self._today = today
        self._now = now
        self._day = today()
        self._spent = spent_today
        self._spent_month = spent_this_month
        self._paused_until: datetime | None = None

    def _roll(self) -> None:
        if (day := self._today()) != self._day:
            if (day.year, day.month) != (self._day.year, self._day.month):
                self._spent_month = 0.0
            self._day, self._spent = day, 0.0

    @property
    def spent_usd(self) -> float:
        """Spent today."""
        self._roll()
        return self._spent

    @property
    def spent_month_usd(self) -> float:
        self._roll()
        return self._spent_month

    def pause_until(self, when: datetime) -> None:
        if self._paused_until is None or when > self._paused_until:
            self._paused_until = when

    def resumes_on(self) -> date | None:
        """The UTC day the AI search runs again; None while it may run."""
        self._roll()
        days = []
        if self._paused_until is not None and self._now() < self._paused_until:
            days.append(self._paused_until.date())
        if self._daily >= 0 and self._spent >= self._daily:
            days.append(self._day + timedelta(days=1))
        if self._monthly >= 0 and self._spent_month >= self._monthly:
            days.append((self._day.replace(day=1) + timedelta(days=32)).replace(day=1))
        return max(days) if days else None

    def exhausted(self) -> bool:
        return self.resumes_on() is not None

    def record(self, usage: Usage) -> float:
        self._roll()
        cost = self._pricing.cost(usage)
        self._spent += cost
        self._spent_month += cost
        return cost
