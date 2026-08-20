from __future__ import annotations

import pytest
from news_claws.config import get_settings


def test_production_rejects_weak_admin_token(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_TOKEN", "too-short")
    monkeypatch.setenv("ALLOWED_HOSTS", "news.example.com")
    monkeypatch.setenv(
        "OUTBOUND_USER_AGENT",
        "NewsClaws/0.1 (contact: ops@company.org)",
    )
    monkeypatch.setenv("SEED_DEMO", "false")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="at least 32 characters"):
        get_settings()
    get_settings.cache_clear()


def test_production_defaults_to_no_demo_data(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_TOKEN", "a-production-secret-that-is-longer-than-32")
    monkeypatch.setenv("ALLOWED_HOSTS", "news.example.com")
    monkeypatch.setenv(
        "OUTBOUND_USER_AGENT",
        "NewsClaws/0.1 (contact: ops@company.org)",
    )
    monkeypatch.delenv("SEED_DEMO", raising=False)
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.seed_demo is False
    assert settings.allowed_hosts == ("news.example.com",)
    assert settings.scheduler_enabled is True
    get_settings.cache_clear()


def test_production_rejects_wildcard_hosts(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("ADMIN_TOKEN", "a-production-secret-that-is-longer-than-32")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    monkeypatch.setenv(
        "OUTBOUND_USER_AGENT",
        "NewsClaws/0.1 (contact: ops@company.org)",
    )
    monkeypatch.setenv("SEED_DEMO", "false")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="Wildcard ALLOWED_HOSTS"):
        get_settings()
    get_settings.cache_clear()


def test_notifications_require_complete_smtp_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("NOTIFICATION_ENABLED", "true")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("SMTP_FROM", "alerts@company.org")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="SMTP_HOST"):
        get_settings()
    get_settings.cache_clear()


def test_openai_compatible_mode_requires_endpoint_and_api_key(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_MODEL", "analysis-model")
    monkeypatch.delenv("LLM_API_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="LLM_API_BASE_URL"):
        get_settings()
    monkeypatch.setenv("LLM_API_BASE_URL", "https://llm.example/v1")
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        get_settings()
    get_settings.cache_clear()


def test_openai_compatible_mode_loads_bounded_runtime_settings(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("LLM_MODEL", "analysis-model")
    monkeypatch.setenv("LLM_API_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "900")
    monkeypatch.setenv("LLM_PER_EVENT_BUDGET", "0.75")
    monkeypatch.setenv("LLM_INPUT_COST_PER_MILLION", "2.5")
    monkeypatch.setenv("LLM_OUTPUT_COST_PER_MILLION", "10")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.llm_api_base_url == "https://llm.example/v1"
    assert settings.llm_timeout_seconds == 12
    assert settings.llm_max_output_tokens == 900
    assert settings.llm_per_event_budget == 0.75
    assert settings.llm_input_cost_per_million == 2.5
    assert settings.llm_output_cost_per_million == 10
    get_settings.cache_clear()
