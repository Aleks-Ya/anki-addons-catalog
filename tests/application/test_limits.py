from datetime import UTC, date, datetime

import pytest

from anki_addons_catalog.application.limits import Budget, Pricing, RateLimiter, TtlCache
from anki_addons_catalog.domain.models import Usage


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_ttl_cache_expires_and_evicts_oldest() -> None:
    clock = Clock()
    cache: TtlCache[str, int] = TtlCache(10, max_entries=2, clock=clock)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    clock.now += 11
    assert cache.get("c") is None


def test_ttl_cache_disabled_with_zero_ttl() -> None:
    cache: TtlCache[str, int] = TtlCache(0)
    cache.put("a", 1)
    assert cache.get("a") is None


def test_rate_limiter_refills() -> None:
    clock = Clock()
    limiter = RateLimiter(per_hour=2, clock=clock)
    assert limiter.allow("ip") and limiter.allow("ip")
    assert not limiter.allow("ip")
    assert limiter.allow("other")
    clock.now += 1800
    assert limiter.allow("ip")
    assert not limiter.allow("ip")


def test_rate_limiter_disabled_with_zero() -> None:
    limiter = RateLimiter(per_hour=0)
    assert all(limiter.allow("ip") for _ in range(100))


PRICING = Pricing(input_per_mtok=2, output_per_mtok=10, cache_read_per_mtok=0.2, cache_write_per_mtok=2.5)


def test_pricing() -> None:
    usage = Usage(input_tokens=1_000_000, output_tokens=100_000, cache_read_input_tokens=1_000_000,
                  cache_creation_input_tokens=400_000)
    assert PRICING.cost(usage) == 2 + 1 + 0.2 + 1


def test_pricing_of_long_prompts() -> None:
    pricing = Pricing(1, 10, 0.1, 1.25, long=Pricing(5, 50, 0.5, 6.25))
    assert pricing.cost(Usage(input_tokens=100_000, output_tokens=1_000_000)) == 0.1 + 10
    assert pricing.cost(Usage(input_tokens=1, cache_read_input_tokens=100_000)) == pytest.approx(5e-6 + 0.05)
    assert pricing.cost(Usage(input_tokens=60_000, cache_creation_input_tokens=60_000)) == pytest.approx(0.3 + 0.375)


def test_daily_budget_resets_next_day() -> None:
    day = [date(2026, 10, 1)]
    budget = Budget(1.0, -1, PRICING, today=lambda: day[0])
    assert not budget.exhausted()
    budget.record(Usage(input_tokens=600_000))
    assert budget.exhausted()
    assert budget.spent_usd == 1.2
    day[0] = date(2026, 10, 2)
    assert not budget.exhausted()
    assert budget.spent_usd == 0


def test_daily_budget_resumes_from_spent_today() -> None:
    day = [date(2026, 10, 1)]
    budget = Budget(1.0, -1, PRICING, today=lambda: day[0], spent_today=1.0)
    assert budget.exhausted()
    day[0] = date(2026, 10, 2)
    assert not budget.exhausted()


def test_monthly_budget_resets_next_month() -> None:
    day = [date(2026, 11, 29)]
    budget = Budget(-1, 1.0, PRICING, today=lambda: day[0], spent_this_month=0.5)
    budget.record(Usage(input_tokens=300_000))
    assert budget.spent_month_usd == pytest.approx(1.1) and budget.resumes_on() == date(2026, 12, 1)
    day[0] = date(2026, 11, 30)
    assert budget.spent_usd == 0 and budget.resumes_on() == date(2026, 12, 1)
    day[0] = date(2026, 12, 1)
    assert budget.spent_month_usd == 0 and budget.resumes_on() is None


def test_budget_resumes_on_the_latest_day() -> None:
    now = [datetime(2026, 11, 23, 5, 0, tzinfo=UTC)]
    budget = Budget(1.0, 2.0, PRICING, today=lambda: now[0].date(), now=lambda: now[0], spent_today=1.0)
    assert budget.resumes_on() == date(2026, 11, 24)  # the daily cap
    budget.pause_until(datetime(2026, 12, 1, tzinfo=UTC))
    budget.pause_until(datetime(2026, 11, 25, tzinfo=UTC))  # an earlier pause does not shorten it
    assert budget.resumes_on() == date(2026, 12, 1) and budget.exhausted()
    now[0] = datetime(2026, 12, 1, tzinfo=UTC)
    assert budget.resumes_on() is None


def test_budget_caps_off_when_negative() -> None:
    budget = Budget(-1, -1, PRICING, spent_today=100, spent_this_month=100)
    assert budget.resumes_on() is None
