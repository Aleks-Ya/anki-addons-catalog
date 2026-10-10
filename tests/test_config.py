from pathlib import Path

import pytest

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
