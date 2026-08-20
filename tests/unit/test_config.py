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
