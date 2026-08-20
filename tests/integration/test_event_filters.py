from pathlib import Path

from news_claws.catalog import bootstrap_catalog
from news_claws.config import Settings
from news_claws.database import get_engine, session_factory
from news_claws.models import Base, EventCluster
from news_claws.services import list_events, seed_demo


def _settings(database_url: str, project_root: Path) -> Settings:
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


def test_combined_filters_run_before_limit(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'filters.db').as_posix()}"
    settings = _settings(database_url, project_root)
    Base.metadata.create_all(get_engine(database_url))

    with session_factory(database_url)() as session:
        bootstrap_catalog(session, settings.config_dir)
        seed_demo(session, settings)
        events = list(session.query(EventCluster).order_by(EventCluster.last_seen.desc()))
        assert len(events) == 2
        wind_event = next(event for event in events if "海上风电" in event.title)
        cloud_event = next(event for event in events if "数据出境" in event.title)
        assert events[0].id == cloud_event.id

        industry = list_events(session, industry_id="isic_3510", limit=1)
        assert [item["id"] for item in industry] == [wind_event.id]

        company = list_events(session, company_id="demo_cloudworks")
        assert [item["id"] for item in company] == [cloud_event.id]

        negative = list_events(session, direction="negative")
        assert [item["id"] for item in negative] == [cloud_event.id]

        high_strength = list_events(session, strength="high")
        assert {item["id"] for item in high_strength} == {wind_event.id, cloud_event.id}

        source = list_events(session, source_id="demo_market_daily")
        assert [item["id"] for item in source] == [wind_event.id]
        assert source[0]["source_ids"] == [
            "demo_business_wire",
            "demo_clean_energy_official",
            "demo_market_daily",
        ]

        chinese = list_events(session, language="zh")
        assert {item["id"] for item in chinese} == {wind_event.id, cloud_event.id}
        assert all(item["languages"] == ["zh"] for item in chinese)
        assert list_events(session, language="en") == []

        assert (
            list_events(
                session,
                industry_id="isic_3510",
                company_id="demo_cloudworks",
            )
            == []
        )
