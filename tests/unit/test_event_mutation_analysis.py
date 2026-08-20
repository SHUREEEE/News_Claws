import asyncio

from news_claws.adapters.llm import LLMProviderError
from news_claws.domain.llm import LLMContractError
from news_claws.services import _analyze_mutated_events


def test_mutation_analysis_reports_dead_without_hiding_committed_event(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_analysis(session, event_id, settings):
        calls.append(event_id)
        if event_id == "evt_old":
            raise LLMContractError("LLM_SCHEMA_INVALID", "invalid", attempts=2)

    monkeypatch.setattr("news_claws.services.analyze_event_configured", fake_analysis)

    status, error = asyncio.run(_analyze_mutated_events(None, ["evt_old", "evt_new"], None))

    assert calls == ["evt_old", "evt_new"]
    assert status == "dead"
    assert error == "evt_old: LLM_SCHEMA_INVALID"


def test_mutation_analysis_reports_retry_wait_for_provider_failure(monkeypatch) -> None:
    async def fake_analysis(session, event_id, settings):
        raise LLMProviderError("provider unavailable")

    monkeypatch.setattr("news_claws.services.analyze_event_configured", fake_analysis)

    status, error = asyncio.run(_analyze_mutated_events(None, ["evt_one"], None))

    assert status == "retry_wait"
    assert error == "evt_one: LLM_PROVIDER_ERROR"
