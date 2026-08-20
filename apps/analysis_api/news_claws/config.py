from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    admin_token: str
    trendradar_mcp_url: str
    trendradar_enabled: bool
    search_provider: str
    llm_provider: str
    llm_model: str
    daily_llm_budget: float
    data_retention_days: int
    seed_demo: bool
    log_level: str
    allowed_hosts: tuple[str, ...]
    max_request_bytes: int
    scheduler_enabled: bool
    scheduler_interval_seconds: int
    scheduler_max_items: int
    outbound_user_agent: str
    project_root: Path
    notification_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    notification_batch_size: int = 100

    def validate(self) -> None:
        if self.app_env not in {"dev", "test", "prod"}:
            raise RuntimeError("APP_ENV must be one of: dev, test, prod")
        if self.daily_llm_budget < 0:
            raise RuntimeError("DAILY_LLM_BUDGET cannot be negative")
        if self.data_retention_days < 1:
            raise RuntimeError("DATA_RETENTION_DAYS must be at least 1")
        if self.max_request_bytes < 1024:
            raise RuntimeError("MAX_REQUEST_BYTES must be at least 1024")
        if not 60 <= self.scheduler_interval_seconds <= 86_400:
            raise RuntimeError("SCHEDULER_INTERVAL_SECONDS must be between 60 and 86400")
        if not 1 <= self.scheduler_max_items <= 100:
            raise RuntimeError("SCHEDULER_MAX_ITEMS must be between 1 and 100")
        if not 1 <= self.smtp_port <= 65_535:
            raise RuntimeError("SMTP_PORT must be between 1 and 65535")
        if not 1 <= self.notification_batch_size <= 500:
            raise RuntimeError("NOTIFICATION_BATCH_SIZE must be between 1 and 500")
        if self.notification_enabled:
            if not self.smtp_host:
                raise RuntimeError("SMTP_HOST is required when notifications are enabled")
            if "@" not in self.smtp_from:
                raise RuntimeError(
                    "SMTP_FROM must be a valid sender when notifications are enabled"
                )
            if self.smtp_username and not self.smtp_password:
                raise RuntimeError("SMTP_PASSWORD is required when SMTP_USERNAME is configured")
        if not self.allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS must contain at least one hostname")
        if self.app_env == "prod":
            weak_tokens = {
                "",
                "dev-admin-token",
                "replace-with-a-long-random-token",
                "change-me",
            }
            if self.admin_token in weak_tokens or len(self.admin_token) < 32:
                raise RuntimeError(
                    "ADMIN_TOKEN must be a unique secret of at least 32 characters in production"
                )
            if self.seed_demo:
                raise RuntimeError("SEED_DEMO must be false in production")
            if (
                len(self.outbound_user_agent) < 20
                or "@" not in self.outbound_user_agent
                or "example." in self.outbound_user_agent.lower()
            ):
                raise RuntimeError(
                    "OUTBOUND_USER_AGENT must identify the service and a real contact email in production"
                )
            if "*" in self.allowed_hosts:
                raise RuntimeError("Wildcard ALLOWED_HOSTS is forbidden in production")

    @property
    def config_dir(self) -> Path:
        return self.project_root / "config"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    app_env = os.getenv("APP_ENV", "dev")
    admin_token = os.getenv("ADMIN_TOKEN", "dev-admin-token" if app_env == "dev" else "")
    settings = Settings(
        app_env=app_env,
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/analysis.db"),
        admin_token=admin_token,
        trendradar_mcp_url=os.getenv("TRENDRADAR_MCP_URL", "http://127.0.0.1:3333/mcp"),
        trendradar_enabled=_as_bool(os.getenv("TRENDRADAR_ENABLED")),
        search_provider=os.getenv("SEARCH_PROVIDER", "disabled"),
        llm_provider=os.getenv("LLM_PROVIDER", "deterministic"),
        llm_model=os.getenv("LLM_MODEL", "rules-v1"),
        daily_llm_budget=float(os.getenv("DAILY_LLM_BUDGET", "5.00")),
        data_retention_days=int(os.getenv("DATA_RETENTION_DAYS", "365")),
        seed_demo=_as_bool(os.getenv("SEED_DEMO"), default=app_env != "prod"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        allowed_hosts=_csv(
            os.getenv("ALLOWED_HOSTS"),
            ("localhost", "127.0.0.1", "testserver") if app_env != "prod" else (),
        ),
        max_request_bytes=int(os.getenv("MAX_REQUEST_BYTES", "1048576")),
        scheduler_enabled=_as_bool(os.getenv("SCHEDULER_ENABLED"), default=app_env == "prod"),
        scheduler_interval_seconds=int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "900")),
        scheduler_max_items=int(os.getenv("SCHEDULER_MAX_ITEMS", "20")),
        outbound_user_agent=os.getenv(
            "OUTBOUND_USER_AGENT",
            "NewsClaws/0.1 (local development)",
        ).strip(),
        project_root=project_root,
        notification_enabled=_as_bool(os.getenv("NOTIFICATION_ENABLED")),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_username=os.getenv("SMTP_USERNAME", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_starttls=_as_bool(os.getenv("SMTP_STARTTLS"), default=True),
        notification_batch_size=int(os.getenv("NOTIFICATION_BATCH_SIZE", "100")),
    )
    settings.validate()
    return settings
