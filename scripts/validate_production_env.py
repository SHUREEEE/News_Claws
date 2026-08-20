from __future__ import annotations

import argparse
import re
from pathlib import Path

PLACEHOLDERS = {
    "",
    "news.example.com",
    "replace-with-at-least-32-random-characters",
    "replace-with-caddy-bcrypt-hash",
    "replace-with-immutable-git-sha",
}
BOOLEAN_VALUES = {"true", "1", "yes", "on", "false", "0", "no", "off"}


def _env_value(raw_value: str, line_number: int) -> str:
    value = raw_value.strip()
    if not value:
        return value
    if value[0] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise ValueError(f"Invalid quoted value on environment line {line_number}")
        return value[1:-1]
    if value[-1] in {"'", '"'}:
        raise ValueError(f"Invalid quoted value on environment line {line_number}")
    return value


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid environment line {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Environment key is empty on line {line_number}")
        if key in values:
            raise ValueError(f"Duplicate environment key {key} on line {line_number}")
        values[key] = _env_value(value, line_number)
    return values


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    required = {
        "APP_ENV",
        "DATABASE_URL",
        "NEWS_CLAWS_IMAGE",
        "NEWS_CLAWS_IMAGE_TAG",
        "ADMIN_TOKEN",
        "DOMAIN",
        "ALLOWED_HOSTS",
        "BASIC_AUTH_USER",
        "BASIC_AUTH_HASH",
        "OUTBOUND_USER_AGENT",
        "SEED_DEMO",
    }
    for key in sorted(required - values.keys()):
        errors.append(f"{key} is required")

    database_url = values.get("DATABASE_URL", "")
    if not re.fullmatch(r"sqlite:////data/[A-Za-z0-9._-]+\.db", database_url):
        errors.append("DATABASE_URL must use a SQLite database file under /data")

    image = values.get("NEWS_CLAWS_IMAGE", "")
    if image != "ghcr.io/shureeee/news_claws":
        errors.append("NEWS_CLAWS_IMAGE must be ghcr.io/shureeee/news_claws")

    image_tag = values.get("NEWS_CLAWS_IMAGE_TAG", "").lower()
    if image_tag in PLACEHOLDERS or not re.fullmatch(r"[0-9a-f]{40}", image_tag):
        errors.append("NEWS_CLAWS_IMAGE_TAG must be an immutable full 40-character Git SHA")

    domain = values.get("DOMAIN", "").lower()
    if domain in PLACEHOLDERS or not re.fullmatch(
        r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
        domain,
    ):
        errors.append("DOMAIN must be a real DNS hostname")

    token = values.get("ADMIN_TOKEN", "")
    if token in PLACEHOLDERS or len(token) < 32:
        errors.append("ADMIN_TOKEN must be a unique secret of at least 32 characters")
    if values.get("APP_ENV") != "prod":
        errors.append("APP_ENV must be prod")
    if values.get("SEED_DEMO", "").lower() not in {"false", "0", "no", "off"}:
        errors.append("SEED_DEMO must be false")
    allowed_hosts = {
        item.strip().lower() for item in values.get("ALLOWED_HOSTS", "").split(",") if item.strip()
    }
    if domain and domain not in allowed_hosts:
        errors.append("ALLOWED_HOSTS must include DOMAIN")
    if "*" in allowed_hosts or any(item.startswith("*.") for item in allowed_hosts):
        errors.append("ALLOWED_HOSTS must not contain wildcards in production")

    basic_user = values.get("BASIC_AUTH_USER", "")
    if basic_user in PLACEHOLDERS or not re.fullmatch(r"[A-Za-z0-9._-]{3,64}", basic_user):
        errors.append("BASIC_AUTH_USER must be configured")
    basic_hash = values.get("BASIC_AUTH_HASH", "")
    bcrypt_match = re.fullmatch(r"\$2[aby]\$(\d{2})\$[./A-Za-z0-9]{53}", basic_hash)
    if (
        basic_hash in PLACEHOLDERS
        or bcrypt_match is None
        or not 4 <= int(bcrypt_match.group(1)) <= 31
    ):
        errors.append("BASIC_AUTH_HASH must be a Caddy-compatible bcrypt hash")

    user_agent = values.get("OUTBOUND_USER_AGENT", "")
    if len(user_agent) < 20 or "@" not in user_agent or "example" in user_agent.lower():
        errors.append("OUTBOUND_USER_AGENT must contain a real contact email")
    for key in (
        "TRENDRADAR_ENABLED",
        "SEED_DEMO",
        "SCHEDULER_ENABLED",
        "NOTIFICATION_ENABLED",
        "SMTP_STARTTLS",
    ):
        if key in values and values[key].lower() not in BOOLEAN_VALUES:
            errors.append(f"{key} must be a boolean value")

    integer_ranges = {
        "DATA_RETENTION_DAYS": (1, 36_500, "365"),
        "MAX_REQUEST_BYTES": (1_024, 10_485_760, "1048576"),
        "SCHEDULER_INTERVAL_SECONDS": (60, 86_400, "900"),
        "SCHEDULER_MAX_ITEMS": (1, 100, "20"),
        "SMTP_PORT": (1, 65_535, "587"),
        "NOTIFICATION_BATCH_SIZE": (1, 500, "100"),
    }
    for key, (minimum, maximum, default) in integer_ranges.items():
        try:
            number = int(values.get(key, default))
        except ValueError:
            number = minimum - 1
        if not minimum <= number <= maximum:
            errors.append(f"{key} must be between {minimum} and {maximum}")

    try:
        daily_budget = float(values.get("DAILY_LLM_BUDGET", "5.00"))
    except ValueError:
        daily_budget = -1
    if daily_budget < 0:
        errors.append("DAILY_LLM_BUDGET must be a non-negative number")

    notifications_enabled = values.get("NOTIFICATION_ENABLED", "false").lower() in {
        "true",
        "1",
        "yes",
        "on",
    }
    if notifications_enabled:
        if not values.get("SMTP_HOST", ""):
            errors.append("SMTP_HOST is required when notifications are enabled")
        if "@" not in values.get("SMTP_FROM", ""):
            errors.append("SMTP_FROM must be a valid sender when notifications are enabled")
        if values.get("SMTP_USERNAME") and not values.get("SMTP_PASSWORD"):
            errors.append("SMTP_PASSWORD is required when SMTP_USERNAME is configured")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate News Claws production environment")
    parser.add_argument("path", type=Path, nargs="?", default=Path(".env.production"))
    args = parser.parse_args()
    if not args.path.is_file():
        raise SystemExit(f"Environment file does not exist: {args.path}")
    try:
        errors = validate(parse_env(args.path))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if errors:
        raise SystemExit("Production environment is invalid:\n- " + "\n- ".join(errors))
    print("Production environment validation passed")


if __name__ == "__main__":
    main()
