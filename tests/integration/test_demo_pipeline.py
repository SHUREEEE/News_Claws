from datetime import UTC, datetime
from pathlib import Path

from news_claws.catalog import bootstrap_catalog
from news_claws.config import Settings
from news_claws.database import get_engine, session_factory
from news_claws.models import (
    Article,
    ArticleVersion,
    Base,
    Entity,
    EventCluster,
    Report,
    Source,
)
from news_claws.services import analyze_event, event_detail, ingest_article, seed_demo
from sqlalchemy import func, select


def make_settings(database_url: str, project_root: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        admin_token="test-token",
        trendradar_mcp_url="http://127.0.0.1:3333/mcp",
        trendradar_enabled=False,
        search_provider="disabled",
        llm_provider="deterministic",
        llm_model="rules-v1",
        daily_llm_budget=1.0,
        data_retention_days=365,
        seed_demo=True,
        log_level="WARNING",
        allowed_hosts=("testserver",),
        max_request_bytes=1_048_576,
        scheduler_enabled=False,
        scheduler_interval_seconds=900,
        scheduler_max_items=20,
        outbound_user_agent="NewsClaws/0.1 (test suite)",
        project_root=project_root,
    )


def test_demo_pipeline_is_traceable_and_idempotent(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'analysis.db').as_posix()}"
    settings = make_settings(database_url, project_root)
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    with session_factory(database_url)() as session:
        bootstrap_catalog(session, settings.config_dir)
        event_ids = seed_demo(session, settings)
        assert len(event_ids) == 2
        assert seed_demo(session, settings) == []
        assert session.scalar(select(func.count()).select_from(Article)) == 5
        assert session.scalar(select(func.count()).select_from(Report)) == 2

        wind_event = session.scalar(
            select(EventCluster).where(EventCluster.title.contains("海上风电"))
        )
        assert wind_event is not None
        detail = event_detail(session, wind_event.id)
        assert len(detail["articles"]) == 3
        assert detail["independent_chain_count"] == 2
        assert detail["verification"].status == "primary_source_confirmed"
        assert detail["industries"]
        assert detail["companies"]

        representative = session.get(Article, wind_event.representative_article_id)
        assert representative is not None
        updated_last_seen = datetime(2026, 8, 21, 9, tzinfo=UTC)
        representative.last_seen_at = updated_last_seen
        existing_report = analyze_event(session, wind_event.id, settings)
        assert existing_report.id == detail["report"].id
        with session_factory(database_url)() as verification_session:
            persisted = verification_session.get(Article, representative.id)
            assert persisted is not None
            assert persisted.last_seen_at.replace(tzinfo=UTC) == updated_last_seen


def test_article_change_creates_version_without_duplicate_article(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'versions.db').as_posix()}"
    settings = make_settings(database_url, project_root)
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    with session_factory(database_url)() as session:
        bootstrap_catalog(session, settings.config_dir)
        source = session.get(Source, "demo_business_wire")
        payload = {
            "url": "https://example.invalid/story/1?utm_source=test",
            "title": "演示：一项可版本化的报道",
            "summary": "第一版摘要",
            "published_at": "2026-08-20T00:00:00Z",
            "language": "zh",
        }
        article, _event, created = ingest_article(session, source, payload)
        session.commit()
        assert created is True
        payload["url"] = "https://example.invalid/story/1"
        payload["summary"] = "第二版摘要与更正数字"
        same_article, _event, created = ingest_article(session, source, payload)
        session.commit()
        assert created is False
        assert same_article.id == article.id
        assert session.scalar(select(func.count()).select_from(Article)) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(ArticleVersion)
                .where(ArticleVersion.article_id == article.id)
            )
            == 2
        )


def test_production_catalog_excludes_demo_sources_and_entities(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'production-catalog.db').as_posix()}"
    engine = get_engine(database_url)
    Base.metadata.create_all(engine)
    with session_factory(database_url)() as session:
        bootstrap_catalog(session, project_root / "config", include_demo=False)
        source_ids = set(session.scalars(select(Source.id)))
        entity_ids = set(session.scalars(select(Entity.id)))
        enabled_sources = list(session.scalars(select(Source).where(Source.enabled.is_(True))))
        assert source_ids
        assert not any(source_id.startswith("demo_") for source_id in source_ids)
        assert not any(entity_id.startswith("demo_") for entity_id in entity_ids)
        assert 40 <= len(enabled_sources) <= 60
        assert {"CN", "US", "EU", "UK", "JP"}.issubset(
            {source.region for source in enabled_sources}
        )
        assert {"zh", "en"}.issubset({source.language for source in enabled_sources})
