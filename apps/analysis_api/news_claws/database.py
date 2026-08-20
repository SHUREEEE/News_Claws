from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings


@lru_cache(maxsize=4)
def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    if url.startswith("sqlite:///./"):
        relative_path = Path(url.removeprefix("sqlite:///./"))
        (get_settings().project_root / relative_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False, "timeout": 5} if url.startswith("sqlite") else {},
        pool_pre_ping=True,
    )

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def upgrade_database(database_url: str | None = None) -> None:
    settings = get_settings()
    config = Config(str(settings.project_root / "alembic.ini"))
    config.set_main_option(
        "script_location", str(settings.project_root / "apps/analysis_api/migrations")
    )
    config.set_main_option("sqlalchemy.url", database_url or settings.database_url)
    command.upgrade(config, "head")


def session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
