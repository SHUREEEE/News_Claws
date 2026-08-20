import asyncio
from copy import deepcopy

import httpx
import pytest
from news_claws.adapters.llm import LLMProviderError, OpenAICompatibleLLM
from news_claws.domain.llm import (
    LLMBudget,
    LLMContractError,
    LLMMessage,
    LLMResult,
    complete_model_analysis,
)
from pydantic import ValidationError


def _valid_output() -> dict[str, object]:
    return {
        "verification_rationale": "The supplied evidence supports a cautious assessment.",
        "industries": [
            {
                "target_id": "industry_1",
                "relevance": 80,
                "direction": "positive",
                "strength": "medium",
                "horizon": "quarters",
                "mechanism": "demand",
                "explanation": "Demand may increase.",
                "confidence": "medium",
                "evidence_ids": ["ev_1"],
                "role": None,
            }
        ],
        "companies": [],
    }


class SequencePort:
    def __init__(self, results: list[LLMResult]) -> None:
        self.results = results
        self.calls = 0

    async def complete_json(self, task, schema, messages, budget, idempotency_key):
        self.calls += 1
        return self.results.pop(0)


def _complete(port: SequencePort):
    return asyncio.run(
        complete_model_analysis(
            port,
            messages=[LLMMessage(role="user", content="analyze")],
            budget=LLMBudget(max_output_tokens=500, max_cost=1.0),
            idempotency_key="event:hardening",
            allowed_evidence_ids={"ev_1"},
            allowed_industry_ids={"industry_1"},
            allowed_company_ids=set(),
        )
    )


def test_duplicate_target_ids_require_a_schema_repair() -> None:
    duplicate = _valid_output()
    duplicate["industries"].append(deepcopy(duplicate["industries"][0]))
    port = SequencePort(
        [
            LLMResult(content=duplicate, estimated_cost=0.1),
            LLMResult(content=_valid_output(), estimated_cost=0.2),
        ]
    )

    result = _complete(port)

    assert result.attempts == 2
    assert result.estimated_cost == pytest.approx(0.3)
    assert port.calls == 2


def test_budget_error_preserves_usage_for_failure_accounting() -> None:
    port = SequencePort(
        [LLMResult(content="not-json", token_input=12, token_output=4, estimated_cost=1.1)]
    )

    with pytest.raises(LLMContractError) as captured:
        _complete(port)

    assert captured.value.code == "BUDGET_EXCEEDED"
    assert captured.value.token_input == 12
    assert captured.value.token_output == 4
    assert captured.value.estimated_cost == pytest.approx(1.1)


@pytest.mark.parametrize(
    "message",
    [
        {"content": None, "refusal": None},
        {"content": None, "refusal": "Request refused"},
    ],
)
def test_openai_adapter_rejects_missing_content_or_refusal(message: dict[str, object]) -> None:
    def responder(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": message}], "usage": {}})

    adapter = OpenAICompatibleLLM(
        base_url="https://llm.example/v1",
        api_key="secret-key",
        model="analysis-model",
        transport=httpx.MockTransport(responder),
    )

    with pytest.raises(LLMProviderError):
        asyncio.run(
            adapter.complete_json(
                "impact",
                {"type": "object"},
                [LLMMessage(role="user", content="analyze")],
                LLMBudget(max_output_tokens=100, max_cost=1.0),
                "job-key",
            )
        )


def test_llm_contract_models_reject_non_finite_costs() -> None:
    with pytest.raises(ValidationError):
        LLMResult(content={}, estimated_cost=float("nan"))
