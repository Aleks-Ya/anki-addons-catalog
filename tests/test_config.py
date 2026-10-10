from pathlib import Path

import pytest

from anki_addons_catalog.application.limits import Pricing
from anki_addons_catalog.config import Settings


def test_api_key_is_read_from_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-test\n")
    settings = Settings(_env_file=tmp_path / ".env")  # type: ignore[call-arg]
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-test"


def test_hf_token_is_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_test")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.hf_token is not None
    assert settings.hf_token.get_secret_value() == "hf_test"


def settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[call-arg, arg-type]


def test_sonnet_is_the_default_model() -> None:
    s = settings()
    assert s.model == "claude-sonnet-5-5"
    profile = s.model_profile()
    assert profile.fallbacks and profile.pricing == Pricing(2.0, 10.0, 0.10, 2.5)


@pytest.mark.parametrize("name", ["haiku", " HAIKU ", "claude-haiku-5-5"])
def test_haiku_by_alias_or_id(name: str) -> None:
    s = settings(model=name)
    assert s.model == "claude-haiku-5-5"
    profile = s.model_profile()
    assert not profile.fallbacks
    assert profile.pricing.input_per_mtok == 0.10 and profile.pricing.long is not None


def test_price_override_wins() -> None:
    pricing = settings(model="haiku", price_output_per_mtok=1.0).model_profile().pricing
    assert (pricing.input_per_mtok, pricing.output_per_mtok) == (0.10, 1.0)


def test_unknown_model_needs_all_prices() -> None:
    with pytest.raises(ValueError, match="claude-x"):
        settings(model="claude-x", price_input_per_mtok=1.0).model_profile()
    profile = settings(model="claude-x", price_input_per_mtok=1, price_output_per_mtok=5, price_cache_read_per_mtok=0.1,
                       price_cache_write_per_mtok=1.25).model_profile()
    assert profile.pricing == Pricing(1, 5, 0.1, 1.25) and not profile.fallbacks
