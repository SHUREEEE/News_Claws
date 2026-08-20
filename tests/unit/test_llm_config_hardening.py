import pytest
from news_claws.config import get_settings

from scripts.validate_production_env import validate


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("DAILY_LLM_BUDGET", "nan", "finite"),
        ("LLM_PER_EVENT_BUDGET", "inf", "finite"),
        ("LLM_TIMEOUT_SECONDS", "nan", "between"),
        ("LLM_INPUT_COST_PER_MILLION", "nan", "finite"),
        ("LLM_OUTPUT_COST_PER_MILLION", "inf", "finite"),
    ],
)
def test_runtime_rejects_non_finite_llm_numbers(monkeypatch, name, value, message) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(name, value)
    get_settings.cache_clear()

    with pytest.raises(RuntimeError, match=message):
        get_settings()

    get_settings.cache_clear()


def test_production_preflight_rejects_non_finite_llm_numbers() -> None:
    values = {
        "APP_ENV": "prod",
        "DATABASE_URL": "sqlite:////data/analysis.db",
        "NEWS_CLAWS_IMAGE": "ghcr.io/shureeee/news_claws",
        "NEWS_CLAWS_IMAGE_TAG": "0123456789abcdef0123456789abcdef01234567",
        "ADMIN_TOKEN": "a-unique-production-token-that-is-long-enough",
        "DOMAIN": "news.example.org",
        "ALLOWED_HOSTS": "news.example.org",
        "BASIC_AUTH_USER": "newsadmin",
        "BASIC_AUTH_HASH": "$2a$14$abcdefghijklmnopqrstuvwxyz012345678901234567890123456",
        "OUTBOUND_USER_AGENT": "NewsClaws/0.1 (contact: ops@company.org)",
        "SEED_DEMO": "false",
        "DAILY_LLM_BUDGET": "nan",
        "LLM_PER_EVENT_BUDGET": "inf",
        "LLM_TIMEOUT_SECONDS": "nan",
        "LLM_INPUT_COST_PER_MILLION": "nan",
        "LLM_OUTPUT_COST_PER_MILLION": "inf",
    }

    errors = validate(values)

    assert any("DAILY_LLM_BUDGET" in error and "finite" in error for error in errors)
    assert any("LLM_PER_EVENT_BUDGET" in error and "finite" in error for error in errors)
    assert any("LLM_TIMEOUT_SECONDS" in error for error in errors)
    assert any("token prices" in error and "finite" in error for error in errors)
