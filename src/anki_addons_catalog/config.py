from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANKI_CATALOG_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str = "https://anki-addons-catalog.com"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    mcp_url: str = "https://ya-alex-anki-addons-mcp.hf.space/mcp"
    mcp_timeout_seconds: float = 120.0
    mcp_keepalive_seconds: int = 600
    mcp_cache_ttl_seconds: int = 3600
    ai_tools: list[str] = [
        "search_addons", "filter_addons", "get_addon", "get_addon_readme", "get_addon_description",
        "check_compatibility", "assess_maintenance", "find_similar_addons", "list_addons_by_author",
        "get_addon_history", "diff_snapshots", "get_statistics", "top_addons", "list_snapshots",
    ]

    anthropic_api_key: SecretStr | None = None
    model: str = "claude-sonnet-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    max_tokens: int = 8000
    max_tool_rounds: int = 6
    max_query_chars: int = 500
    fallbacks_enabled: bool = True
    price_input_per_mtok: float = 2.0
    price_output_per_mtok: float = 10.0
    price_cache_read_per_mtok: float = 0.2
    price_cache_write_per_mtok: float = 2.5

    daily_budget_usd: float = 5.0
    rate_limit_per_hour: int = 20
    answer_cache_ttl_seconds: int = 86400

    turnstile_site_key: str | None = None
    turnstile_secret: SecretStr | None = None
    session_secret: SecretStr | None = None
    pass_ttl_seconds: int = 3600
