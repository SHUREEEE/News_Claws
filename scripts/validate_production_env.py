from __future__ import annotations

import argparse
import re
from pathlib import Path

PLACEHOLDERS = {
    "",
    "news.example.com",
    "replace-with-at-least-32-random-characters",
    "replace-with-caddy-bcrypt-hash",
}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid environment line {line_number}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    required = {
        "APP_ENV",
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
    if domain and domain not in {
        item.strip().lower() for item in values.get("ALLOWED_HOSTS", "").split(",")
    }:
        errors.append("ALLOWED_HOSTS must include DOMAIN")

    basic_user = values.get("BASIC_AUTH_USER", "")
    if basic_user in PLACEHOLDERS or len(basic_user) < 3:
        errors.append("BASIC_AUTH_USER must be configured")
    basic_hash = values.get("BASIC_AUTH_HASH", "")
    if basic_hash in PLACEHOLDERS or not basic_hash.startswith(("$2a$", "$2b$", "$2y$")):
        errors.append("BASIC_AUTH_HASH must be a Caddy-compatible bcrypt hash")

    user_agent = values.get("OUTBOUND_USER_AGENT", "")
    if len(user_agent) < 20 or "@" not in user_agent or "example" in user_agent.lower():
        errors.append("OUTBOUND_USER_AGENT must contain a real contact email")
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
        try:
            smtp_port = int(values.get("SMTP_PORT", "587"))
        except ValueError:
            smtp_port = 0
        if not 1 <= smtp_port <= 65_535:
            errors.append("SMTP_PORT must be between 1 and 65535")
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
