from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from news_claws.catalog import bootstrap_catalog
from news_claws.config import Settings
from news_claws.database import get_engine, session_factory
from news_claws.domain.llm import LLMContractError, LLMResult
from news_claws.models import AnalysisRun, Base, Claim, PipelineJob, Report, Source
from news_claws.services import analyze_event_configured, ingest_article
from sqlalchemy import func, select


def _settings(database_url: str, project_root: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        admin_token="test-token",
        trendradar_mcp_url="http://127.0.0.1:3333/mcp",
        trendradar_enabled=False,
        search_provider="disabled",
        llm_provider="openai-compatible",
        llm_model="test-structured-model",
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
        llm_timeout_seconds=5,
        llm_max_output_tokens=1_000,
        llm_per_event_budget=1.0,
    )


def _event(session, settings: Settings):
    bootstrap_catalog(session, settings.config_dir)
    source = session.get(Source, "us_sec_press")
    assert source is not None
    _article, event, _created = ingest_article(
        session,
        source,
        {
            "url": "https://www.sec.gov/news/press-release-test",
            "title": "Grid investment increases demand for energy infrastructure",
            "summary": "The official release supports new electricity grid investment.",
            "published_at": "2026-08-21T01:00:00Z",
        },
    )
    session.commit()
    return event


class RepairThenValidPort:
    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(self, task, schema, messages, budget, idempotency_key):
        self.calls += 1
        if self.calls == 1:
            return LLMResult(content="invalid-json", token_input=10, token_output=2)
        context = json.loads(messages[1].content)
        evidence_id = context["evidence"][0]["id"]
        return LLMResult(
            content={
                "verification_rationale": "The impact uses the supplied official evidence.",
                "industries": [
                    {
                        "target_id": "isic_3510",
                        "relevance": 88,
                        "direction": "positive",
                        "strength": "high",
                        "horizon": "quarters",
                        "mechanism": "demand",
                        "explanation": "Grid investment can raise equipment and services demand.",
                        "confidence": "high",
                        "evidence_ids": [evidence_id],
                        "role": None,
                    }
                ],
                "companies": [
                    {
                        "target_id": "demo_green_grid",
                        "relevance": 70,
                        "direction": "positive",
                        "strength": "medium",
                        "horizon": "quarters",
                        "mechanism": "demand",
                        "explanation": "The mapped grid supplier may see indirect demand exposure.",
                        "confidence": "medium",
                        "evidence_ids": [evidence_id],
                        "role": "supplier",
                    }
                ],
            },
            token_input=20,
            token_output=30,
            estimated_cost=0.2,
        )


class AlwaysInvalidPort:
    def __init__(self) -> None:
        self.calls = 0

    async def complete_json(self, task, schema, messages, budget, idempotency_key):
        self.calls += 1
        return LLMResult(
            content="still-not-json", token_input=5, token_output=2, estimated_cost=0.15
        )


def test_repaired_model_output_is_validated_before_report_persistence(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'llm-success.db').as_posix()}"
    settings = _settings(database_url, project_root)
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        event = _event(session, settings)
        port = RepairThenValidPort()

        report = asyncio.run(analyze_event_configured(session, event.id, settings, llm_port=port))

        assert port.calls == 2
        assert report.content_json["industries"][0]["target_id"] == "isic_3510"
        assert report.content_json["companies"][0]["target_id"] == "demo_green_grid"
        job = session.scalar(select(PipelineJob))
        assert job is not None
        assert job.status == "succeeded"
        assert job.attempts == 2
        impact_run = session.scalar(
            select(AnalysisRun)
            .where(AnalysisRun.stage == "impact")
            .order_by(AnalysisRun.created_at.desc())
        )
        assert impact_run is not None
        assert impact_run.status == "succeeded"
        assert impact_run.cost == 0.2


def test_invalid_model_output_twice_creates_dead_job_and_no_report(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'llm-dead.db').as_posix()}"
    settings = _settings(database_url, project_root)
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        event = _event(session, settings)
        port = AlwaysInvalidPort()

        with pytest.raises(LLMContractError) as captured:
            asyncio.run(analyze_event_configured(session, event.id, settings, llm_port=port))

        assert captured.value.code == "LLM_SCHEMA_INVALID"
        assert captured.value.attempts == 2
        assert port.calls == 2
        assert session.scalar(select(func.count()).select_from(Report)) == 0
        assert session.scalar(select(func.count()).select_from(Claim)) == 0
        job = session.scalar(select(PipelineJob))
        assert job is not None
        assert job.status == "dead"
        assert job.attempts == 2
        assert "LLM_SCHEMA_INVALID" in (job.last_error or "")
        runs = list(session.scalars(select(AnalysisRun)))
        assert len(runs) == 1
        assert runs[0].status == "dead"
        assert runs[0].output_json["error_code"] == "LLM_SCHEMA_INVALID"
        assert runs[0].cost == pytest.approx(0.3)
        assert runs[0].output_json["token_input"] == 10
        assert runs[0].output_json["token_output"] == 4


def test_explicit_reanalysis_can_retry_a_dead_model_job(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[2]
    database_url = f"sqlite:///{(tmp_path / 'llm-manual-retry.db').as_posix()}"
    settings = _settings(database_url, project_root)
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        event = _event(session, settings)
        with pytest.raises(LLMContractError):
            asyncio.run(
                analyze_event_configured(
                    session,
                    event.id,
                    settings,
                    llm_port=AlwaysInvalidPort(),
                )
            )
        assert session.scalar(select(func.count()).select_from(Report)) == 0

        report = asyncio.run(
            analyze_event_configured(
                session,
                event.id,
                settings,
                llm_port=RepairThenValidPort(),
                force_retry=True,
            )
        )

        assert report.id
        job = session.scalar(select(PipelineJob))
        assert job is not None
        assert job.status == "succeeded"
        assert job.attempts == 2
