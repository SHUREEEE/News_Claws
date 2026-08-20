import asyncio
import json
from pathlib import Path

from news_claws.catalog import bootstrap_catalog
from news_claws.config import Settings
from news_claws.database import get_engine, session_factory
from news_claws.domain.llm import LLMResult
from news_claws.models import Base, Industry, Source
from news_claws.services import analyze_event_configured, ingest_article


class BoundedContextPort:
    async def complete_json(self, task, schema, messages, budget, idempotency_key):
        assert len(messages[1].content) <= 40_000
        context = json.loads(messages[1].content)
        assert len(context["evidence"]) <= 12
        assert len(context["allowed_industries"]) == 24
        assert len(context["allowed_companies"]) <= 12
        assert all(
            len(industry["keywords"]) <= 6
            and all(len(keyword) <= 48 for keyword in industry["keywords"])
            for industry in context["allowed_industries"]
        )
        return LLMResult(
            content={
                "verification_rationale": "The bounded evidence supports cautious analysis.",
                "industries": [
                    {
                        "target_id": context["allowed_industries"][0]["id"],
                        "relevance": 80,
                        "direction": "positive",
                        "strength": "medium",
                        "horizon": "quarters",
                        "mechanism": "demand",
                        "explanation": "Demand may increase.",
                        "confidence": "medium",
                        "evidence_ids": [context["evidence"][0]["id"]],
                        "role": None,
                    }
                ],
                "companies": [],
            },
            estimated_cost=0.01,
        )


def test_large_industry_catalog_produces_a_bounded_llm_prompt(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'bounded-prompt.db').as_posix()}"
    settings = Settings(
        app_env="test",
        database_url=database_url,
        admin_token="test-token",
        trendradar_mcp_url="http://127.0.0.1:3333/mcp",
        trendradar_enabled=False,
        search_provider="disabled",
        llm_provider="openai-compatible",
        llm_model="bounded-model",
        daily_llm_budget=5.0,
        data_retention_days=365,
        seed_demo=False,
        log_level="WARNING",
        allowed_hosts=("testserver",),
        max_request_bytes=1_048_576,
        scheduler_enabled=False,
        scheduler_interval_seconds=900,
        scheduler_max_items=20,
        outbound_user_agent="NewsClaws/0.1 (test suite)",
        project_root=project_root,
        llm_api_base_url="https://llm.example/v1",
        llm_api_key="test-key",
        llm_per_event_budget=1.0,
    )
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        bootstrap_catalog(session, settings.config_dir)
        session.add_all(
            Industry(
                id=f"stress_{index:03d}",
                code=f"S{index:03d}",
                name=f"Stress industry {index}",
                keywords=[f"keyword-{index}-{item}-" + "x" * 120 for item in range(20)],
            )
            for index in range(100)
        )
        source = session.get(Source, "us_sec_press")
        assert source is not None
        _article, event, _created = ingest_article(
            session,
            source,
            {
                "url": "https://www.sec.gov/news/bounded-prompt",
                "title": "Grid investment increases energy infrastructure demand",
                "summary": "The official release announces audited grid investment.",
                "published_at": "2026-08-21T01:00:00Z",
            },
        )
        session.commit()

        report = asyncio.run(
            analyze_event_configured(session, event.id, settings, llm_port=BoundedContextPort())
        )

        assert report.id
