import asyncio
import json

import httpx
import pytest
from news_claws.adapters.llm import OpenAICompatibleLLM
from news_claws.domain.llm import (
    LLMBudget,
    LLMContractError,
    LLMMessage,
    LLMResult,
    ModelAnalysisOutput,
    complete_model_analysis,
)


class SequencePort:
    def __init__(self, results: list[LLMResult]) -> None:
        self.results = results
        self.calls: list[dict[str, object]] = []

    async def complete_json(self, task, schema, messages, budget, idempotency_key):
        self.calls.append(
            {
                "task": task,
                "schema": schema,
                "messages": messages,
                "budget": budget,
                "idempotency_key": idempotency_key,
            }
        )
        return self.results.pop(0)


def _valid_output(evidence_id: str = "ev_1") -> dict[str, object]:
    return {
        "verification_rationale": "Evidence supports a cautious impact assessment.",
        "industries": [
            {
                "target_id": "industry_1",
                "relevance": 82,
                "direction": "positive",
                "strength": "medium",
                "horizon": "quarters",
                "mechanism": "demand",
                "explanation": "Demand may increase.",
                "confidence": "medium",
                "evidence_ids": [evidence_id],
                "role": None,
            }
        ],
        "companies": [],
    }


def _complete(port: SequencePort):
    return asyncio.run(
        complete_model_analysis(
            port,
            messages=[LLMMessage(role="user", content="analyze")],
            budget=LLMBudget(max_output_tokens=500, max_cost=1.0),
            idempotency_key="event:one",
            allowed_evidence_ids={"ev_1"},
            allowed_industry_ids={"industry_1"},
            allowed_company_ids=set(),
        )
    )


def test_invalid_json_receives_exactly_one_successful_repair_call() -> None:
    port = SequencePort(
        [
            LLMResult(content="not-json", token_input=5, token_output=2),
            LLMResult(content=_valid_output(), token_input=7, token_output=11),
        ]
    )

    result = _complete(port)

    assert result.attempts == 2
    assert result.token_input == 12
    assert result.token_output == 13
    assert [call["task"] for call in port.calls] == [
        "event-impact-analysis",
        "event-impact-analysis-repair",
    ]
    assert port.calls[1]["idempotency_key"] == "event:one:repair"


def test_invalid_json_twice_is_a_dead_contract_error() -> None:
    port = SequencePort([LLMResult(content="{"), LLMResult(content="still invalid")])

    with pytest.raises(LLMContractError) as captured:
        _complete(port)

    assert captured.value.code == "LLM_SCHEMA_INVALID"
    assert captured.value.attempts == 2
    assert len(port.calls) == 2


def test_invalid_evidence_id_fails_without_a_repair_call() -> None:
    port = SequencePort([LLMResult(content=_valid_output("ev_outside_whitelist"))])

    with pytest.raises(LLMContractError) as captured:
        _complete(port)

    assert captured.value.code == "EVIDENCE_ID_INVALID"
    assert captured.value.attempts == 1
    assert len(port.calls) == 1


def test_exhausted_budget_prevents_a_repair_call() -> None:
    port = SequencePort(
        [LLMResult(content="not-json", estimated_cost=1.01), LLMResult(content=_valid_output())]
    )

    with pytest.raises(LLMContractError) as captured:
        _complete(port)

    assert captured.value.code == "BUDGET_EXCEEDED"
    assert captured.value.attempts == 1
    assert len(port.calls) == 1


def test_openai_compatible_adapter_sends_strict_json_schema_request() -> None:
    captured: dict[str, object] = {}

    def responder(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["idempotency_key"] = request.headers["idempotency-key"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": _valid_output(), "refusal": None}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 10},
            },
        )

    adapter = OpenAICompatibleLLM(
        base_url="https://llm.example/v1",
        api_key="secret-key",
        model="analysis-model",
        input_cost_per_million=1.0,
        output_cost_per_million=2.0,
        transport=httpx.MockTransport(responder),
    )
    result = asyncio.run(
        adapter.complete_json(
            "impact analysis",
            {"type": "object", "additionalProperties": False},
            [LLMMessage(role="user", content="analyze")],
            LLMBudget(max_output_tokens=321, max_cost=1.0),
            "job-key",
        )
    )

    payload = captured["payload"]
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer secret-key"
    assert captured["idempotency_key"] == "job-key"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["max_completion_tokens"] == 321
    assert result.token_input == 9
    assert result.token_output == 10
    assert result.estimated_cost == pytest.approx(0.000029)


def test_model_schema_requires_every_property_for_strict_structured_outputs() -> None:
    schema = ModelAnalysisOutput.model_json_schema()
    assert set(schema["required"]) == set(schema["properties"])
    impact_schema = schema["$defs"]["ModelImpact"]
    assert set(impact_schema["required"]) == set(impact_schema["properties"])
    assert schema["additionalProperties"] is False
    assert impact_schema["additionalProperties"] is False
