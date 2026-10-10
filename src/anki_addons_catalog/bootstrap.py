import logging
import os
from pathlib import Path

import anthropic
from fastapi import FastAPI

from anki_addons_catalog.adapters.claude.llm import ClaudeLlm
from anki_addons_catalog.adapters.mcp.catalog import McpCatalog
from anki_addons_catalog.application.ask import AskService
from anki_addons_catalog.application.catalog import CatalogService
from anki_addons_catalog.application.limits import DailyBudget, Pricing, RateLimiter
from anki_addons_catalog.application.usage import AI_COST_USD, MEMORY, UsageStats
from anki_addons_catalog.config import Settings
from anki_addons_catalog.domain.ports import CatalogPort, LlmPort
from anki_addons_catalog.interface.web.app import WebContext, create_web_app
from anki_addons_catalog.interface.web.security import HumanCheck

log = logging.getLogger(__name__)

PERSISTENT_STORAGE = Path("/data")


def _secret(value: object) -> str | None:
    return value.get_secret_value() if value is not None else None  # type: ignore[attr-defined]


def create_llm(settings: Settings) -> LlmPort:
    client = anthropic.AsyncAnthropic(api_key=_secret(settings.anthropic_api_key))  # None: ANTHROPIC_API_KEY
    return ClaudeLlm(client, settings.model, settings.effort, settings.max_tokens, settings.fallbacks_enabled)


def create_usage(settings: Settings, storage: Path = PERSISTENT_STORAGE) -> UsageStats:
    """The configured SQLite file, else in memory with a backup in the Space's mounted volume, else in memory only."""
    if settings.usage_db:
        return UsageStats(settings.usage_db)
    if storage.is_dir() and os.access(storage, os.W_OK):
        return UsageStats(MEMORY, backup=str(storage / "usage.sqlite3"))
    return UsageStats(MEMORY)


def create_app(settings: Settings, catalog: CatalogPort | None = None, llm: LlmPort | None = None) -> FastAPI:
    mcp = None
    if catalog is None:
        hf_token = _secret(settings.hf_token)
        log.info("MCP requests: %s", "authenticated with HF_TOKEN" if hf_token else "anonymous")
        mcp = McpCatalog(settings.mcp_url, settings.mcp_timeout_seconds,
                         headers={"Authorization": f"Bearer {hf_token}"} if hf_token else None)
    port: CatalogPort = catalog or mcp  # type: ignore[assignment]
    catalog_service = CatalogService(port, settings.mcp_cache_ttl_seconds)
    pricing = Pricing(settings.price_input_per_mtok, settings.price_output_per_mtok,
                      settings.price_cache_read_per_mtok, settings.price_cache_write_per_mtok)
    usage = create_usage(settings)
    log.info("Usage statistics: %s", f"saved to {usage.backup}" if usage.backup else
             usage.path if usage.persistent else "in memory (reset on restart)")
    budget = DailyBudget(settings.daily_budget_usd, pricing, spent_today=usage.today(AI_COST_USD))
    ask = AskService(port, llm or create_llm(settings), budget,
                     allowed_tools=settings.ai_tools, max_tool_rounds=settings.max_tool_rounds,
                     answer_cache_ttl_seconds=settings.answer_cache_ttl_seconds,
                     snapshot=catalog_service.latest_snapshot, usage=usage)
    human = HumanCheck(settings.turnstile_site_key, _secret(settings.turnstile_secret),
                       _secret(settings.session_secret), settings.pass_ttl_seconds)
    ctx = WebContext(catalog_port=port, catalog=catalog_service, ask=ask, human=human,
                     limiter=RateLimiter(settings.rate_limit_per_hour), public_url=settings.public_url.rstrip("/"),
                     max_query_chars=settings.max_query_chars, keepalive_seconds=settings.mcp_keepalive_seconds,
                     usage=usage, admin_token=_secret(settings.admin_token),
                     daily_budget_usd=settings.daily_budget_usd, usage_save_seconds=settings.usage_save_seconds)

    async def close() -> None:
        try:
            if mcp:
                await mcp.close()
        finally:
            usage.close()

    return create_web_app(ctx, close=close)
