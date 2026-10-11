from dataclasses import dataclass, replace
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from anki_addons_catalog.application.limits import Pricing


@dataclass(frozen=True)
class ModelProfile:
    """What the app needs to know about a Claude model: its prices and whether it has the server-side fallback."""
    pricing: Pricing
    fallbacks: bool


# Prices per MTok from https://platform.claude.com/docs/en/about-claude/pricing (5-minute cache writes).
MODELS: dict[str, ModelProfile] = {
    "claude-sonnet-5-5": ModelProfile(Pricing(2.0, 10.0, 0.10, 2.5), fallbacks=True),
    "claude-haiku-5-5": ModelProfile(Pricing(0.10, 0.50, 0.01, 0.125, long=Pricing(0.50, 2.50, 0.05, 0.625)),
                                     fallbacks=False),
}
MODEL_ALIASES = {"sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANKI_CATALOG_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str = "https://www.anki-addons-catalog.com"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    mcp_url: str = "https://ya-alex-anki-addons-mcp.hf.space/mcp"
    hf_token: SecretStr | None = Field(default=None, validation_alias=AliasChoices("HF_TOKEN", "ANKI_CATALOG_HF_TOKEN"))
    mcp_timeout_seconds: float = 120.0
    mcp_keepalive_seconds: int = 600
    mcp_cache_ttl_seconds: int = 3600
    ai_tools: list[str] = [
        "search_addons", "filter_addons", "get_addon", "get_addon_readme", "get_addon_description",
        "check_compatibility", "assess_maintenance", "find_similar_addons", "list_addons_by_author",
        "get_addon_history", "diff_snapshots", "get_statistics", "top_addons", "list_tags", "list_snapshots",
    ]

    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "ANKI_CATALOG_ANTHROPIC_API_KEY"))
    model: str = "sonnet"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    max_tokens: int = 8000
    max_tool_rounds: int = 6
    max_query_chars: int = 500
    fallbacks_enabled: bool = True
    price_input_per_mtok: float | None = None  # override the model's prices; required for a model not in MODELS
    price_output_per_mtok: float | None = None
    price_cache_read_per_mtok: float | None = None
    price_cache_write_per_mtok: float | None = None

    daily_budget_usd: float = 5.0
    rate_limit_per_hour: int = 20
    answer_cache_ttl_seconds: int = 86400

    turnstile_site_key: str | None = None
    turnstile_secret: SecretStr | None = None
    session_secret: SecretStr | None = None
    pass_ttl_seconds: int = 3600

    usage_db: str | None = None
    usage_save_seconds: int = 300
    question_days: int = 90
    admin_token: SecretStr | None = None

    @field_validator("model")
    @classmethod
    def _resolve_alias(cls, value: str) -> str:
        value = value.strip()
        return MODEL_ALIASES.get(value.lower(), value)

    def model_profile(self) -> ModelProfile:
        """The profile of `model` with the configured price overrides; an unknown model needs all four prices."""
        prices = {"input_per_mtok": self.price_input_per_mtok, "output_per_mtok": self.price_output_per_mtok,
                  "cache_read_per_mtok": self.price_cache_read_per_mtok,
                  "cache_write_per_mtok": self.price_cache_write_per_mtok}
        overrides = {name: price for name, price in prices.items() if price is not None}
        profile = MODELS.get(self.model)
        if profile is None:
            if len(overrides) < len(prices):
                raise ValueError(f"Unknown model {self.model!r}: set all ANKI_CATALOG_PRICE_* settings or use one of "
                                 f"{', '.join([*MODEL_ALIASES, *MODELS])}")
            return ModelProfile(Pricing(**overrides), fallbacks=False)  # type: ignore[arg-type]
        return replace(profile, pricing=replace(profile.pricing, **overrides)) if overrides else profile  # type: ignore[arg-type]
