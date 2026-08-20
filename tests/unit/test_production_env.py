from pathlib import Path

import pytest

from scripts.validate_production_env import parse_env, validate


def valid_environment() -> dict[str, str]:
    return {
        "APP_ENV": "prod",
        "DATABASE_URL": "sqlite:////data/analysis.db",
        "NEWS_CLAWS_IMAGE": "ghcr.io/shureeee/news_claws",
        "NEWS_CLAWS_IMAGE_TAG": "0123456789abcdef0123456789abcdef01234567",
        "ADMIN_TOKEN": "a-unique-production-token-that-is-long-enough",
        "DOMAIN": "news.example.org",
        "ALLOWED_HOSTS": "news.example.org,127.0.0.1,localhost",
        "BASIC_AUTH_USER": "newsadmin",
        "BASIC_AUTH_HASH": "$2a$14$abcdefghijklmnopqrstuvwxyz012345678901234567890123456",
        "OUTBOUND_USER_AGENT": "NewsClaws/0.1 (contact: ops@company.org)",
        "SEED_DEMO": "false",
    }


def test_valid_production_environment_passes() -> None:
    assert validate(valid_environment()) == []


def test_placeholder_production_environment_fails_closed() -> None:
    values = valid_environment()
    values["DOMAIN"] = "news.example.com"
    values["ADMIN_TOKEN"] = "replace-with-at-least-32-random-characters"
    values["BASIC_AUTH_HASH"] = "replace-with-caddy-bcrypt-hash"
    errors = validate(values)
    assert any("DOMAIN" in error for error in errors)
    assert any("ADMIN_TOKEN" in error for error in errors)
    assert any("BASIC_AUTH_HASH" in error for error in errors)


def test_gateway_credentials_and_host_wildcards_fail_closed() -> None:
    values = valid_environment()
    values["BASIC_AUTH_USER"] = "invalid user"
    values["BASIC_AUTH_HASH"] = "$2a$03$" + "a" * 53
    values["ALLOWED_HOSTS"] += ",*"
    errors = validate(values)
    assert any("BASIC_AUTH_USER" in error for error in errors)
    assert any("BASIC_AUTH_HASH" in error for error in errors)
    assert any("wildcards" in error for error in errors)


def test_enabled_notifications_require_smtp_secrets() -> None:
    values = valid_environment()
    values["NOTIFICATION_ENABLED"] = "true"
    values["SMTP_FROM"] = "alerts@company.org"
    values["SMTP_USERNAME"] = "mailer"
    errors = validate(values)
    assert any("SMTP_HOST" in error for error in errors)
    assert any("SMTP_PASSWORD" in error for error in errors)


def test_runtime_numeric_and_boolean_settings_are_preflighted() -> None:
    values = valid_environment()
    values.update(
        {
            "SCHEDULER_ENABLED": "sometimes",
            "SCHEDULER_INTERVAL_SECONDS": "30",
            "NOTIFICATION_BATCH_SIZE": "501",
            "SMTP_PORT": "not-a-port",
            "DAILY_LLM_BUDGET": "-1",
        }
    )
    errors = validate(values)
    assert any("SCHEDULER_ENABLED" in error for error in errors)
    assert any("SCHEDULER_INTERVAL_SECONDS" in error for error in errors)
    assert any("NOTIFICATION_BATCH_SIZE" in error for error in errors)
    assert any("SMTP_PORT" in error for error in errors)
    assert any("DAILY_LLM_BUDGET" in error for error in errors)


def test_production_storage_and_image_tag_are_immutable() -> None:
    values = valid_environment()
    values["DATABASE_URL"] = "sqlite:///./data/analysis.db"
    values["NEWS_CLAWS_IMAGE"] = "news-claws-analysis-api"
    values["NEWS_CLAWS_IMAGE_TAG"] = "0123456789ab"
    errors = validate(values)
    assert any("DATABASE_URL" in error for error in errors)
    assert any("NEWS_CLAWS_IMAGE" in error for error in errors)
    assert any("NEWS_CLAWS_IMAGE_TAG" in error for error in errors)


def test_parse_env_preserves_single_quoted_bcrypt_hash(tmp_path: Path) -> None:
    path = tmp_path / "production.env"
    path.write_text(
        "BASIC_AUTH_HASH='$2a$14$literal-dollar-signs'\nDOMAIN=news.company.org\n",
        encoding="utf-8",
    )
    assert parse_env(path) == {
        "BASIC_AUTH_HASH": "$2a$14$literal-dollar-signs",
        "DOMAIN": "news.company.org",
    }


def test_parse_env_rejects_duplicate_or_unbalanced_values(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.env"
    duplicate.write_text("DOMAIN=one.example.org\nDOMAIN=two.example.org\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate environment key"):
        parse_env(duplicate)

    unbalanced = tmp_path / "unbalanced.env"
    unbalanced.write_text("BASIC_AUTH_HASH='$2a$14$broken\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid quoted value"):
        parse_env(unbalanced)
