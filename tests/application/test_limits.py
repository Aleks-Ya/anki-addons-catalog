from datetime import date

from anki_addons_catalog.application.limits import DailyBudget, Pricing, RateLimiter, TtlCache
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


def test_daily_budget_resets_next_day() -> None:
    day = [date(2026, 10, 1)]
    budget = DailyBudget(1.0, PRICING, today=lambda: day[0])
    assert not budget.exhausted()
    budget.record(Usage(input_tokens=600_000))
    assert budget.exhausted()
    assert budget.spent_usd == 1.2
    day[0] = date(2026, 10, 2)
    assert not budget.exhausted()
    assert budget.spent_usd == 0
