from scripts.validate_production_env import validate


def valid_environment() -> dict[str, str]:
    return {
        "APP_ENV": "prod",
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


def test_enabled_notifications_require_smtp_secrets() -> None:
    values = valid_environment()
    values["NOTIFICATION_ENABLED"] = "true"
    values["SMTP_FROM"] = "alerts@company.org"
    values["SMTP_USERNAME"] = "mailer"
    errors = validate(values)
    assert any("SMTP_HOST" in error for error in errors)
    assert any("SMTP_PASSWORD" in error for error in errors)
