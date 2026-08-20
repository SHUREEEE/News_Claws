from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StrictLLMModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class LLMMessage(StrictLLMModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=40_000)


class LLMBudget(StrictLLMModel):
    max_output_tokens: int = Field(ge=1, le=20_000)
    max_cost: float = Field(ge=0)


class LLMResult(StrictLLMModel):
    content: str | dict[str, Any]
    token_input: int = Field(default=0, ge=0)
    token_output: int = Field(default=0, ge=0)
    estimated_cost: float = Field(default=0.0, ge=0)


class LLMPort(Protocol):
    async def complete_json(
        self,
        task: str,
        schema: dict[str, Any],
        messages: list[LLMMessage],
        budget: LLMBudget,
        idempotency_key: str,
    ) -> LLMResult: ...


class ModelImpact(StrictLLMModel):
    target_id: str = Field(min_length=1, max_length=80)
    relevance: int = Field(ge=0, le=100)
    direction: Literal["positive", "negative", "mixed", "neutral", "unknown"]
    strength: Literal["low", "medium", "high"]
    horizon: str = Field(min_length=1, max_length=24)
    mechanism: str = Field(min_length=1, max_length=32)
    explanation: str = Field(min_length=1, max_length=1_000)
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    role: str | None = Field(max_length=32)


class ModelAnalysisOutput(StrictLLMModel):
    verification_rationale: str = Field(min_length=1, max_length=2_000)
    industries: list[ModelImpact] = Field(max_length=3)
    companies: list[ModelImpact] = Field(max_length=5)


class LLMContractError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        attempts: int,
        token_input: int = 0,
        token_output: int = 0,
        estimated_cost: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.attempts = attempts
        self.token_input = token_input
        self.token_output = token_output
        self.estimated_cost = estimated_cost


@dataclass(frozen=True)
class ValidatedLLMOutput:
    output: ModelAnalysisOutput
    attempts: int
    token_input: int
    token_output: int
    estimated_cost: float


def _validation_message(error: Exception) -> str:
    if isinstance(error, json.JSONDecodeError):
        return "Output is not valid JSON."
    if isinstance(error, ValidationError):
        return json.dumps(
            error.errors(include_input=False, include_url=False),
            ensure_ascii=False,
            separators=(",", ":"),
        )[:8_000]
    return str(error)[:8_000]


def _parse_output(content: str | dict[str, Any]) -> ModelAnalysisOutput:
    value = json.loads(content) if isinstance(content, str) else content
    return ModelAnalysisOutput.model_validate(value)


def _validate_references(
    output: ModelAnalysisOutput,
    *,
    allowed_evidence_ids: set[str],
    allowed_industry_ids: set[str],
    allowed_company_ids: set[str],
    attempts: int,
    token_input: int,
    token_output: int,
    estimated_cost: float,
) -> None:
    industry_ids = [impact.target_id for impact in output.industries]
    company_ids = [impact.target_id for impact in output.companies]
    if len(industry_ids) != len(set(industry_ids)):
        raise ValueError("Industry target_id values must be unique")
    if len(company_ids) != len(set(company_ids)):
        raise ValueError("Company target_id values must be unique")

    for impact in output.industries:
        if impact.target_id not in allowed_industry_ids:
            raise ValueError(f"Unknown industry target_id: {impact.target_id}")
        unknown = set(impact.evidence_ids) - allowed_evidence_ids
        if unknown:
            raise LLMContractError(
                "EVIDENCE_ID_INVALID",
                "Model cited evidence outside the supplied whitelist",
                attempts=attempts,
                token_input=token_input,
                token_output=token_output,
                estimated_cost=estimated_cost,
            )
    for impact in output.companies:
        if impact.target_id not in allowed_company_ids:
            raise ValueError(f"Unknown company target_id: {impact.target_id}")
        unknown = set(impact.evidence_ids) - allowed_evidence_ids
        if unknown:
            raise LLMContractError(
                "EVIDENCE_ID_INVALID",
                "Model cited evidence outside the supplied whitelist",
                attempts=attempts,
                token_input=token_input,
                token_output=token_output,
                estimated_cost=estimated_cost,
            )


async def complete_model_analysis(
    port: LLMPort,
    *,
    messages: list[LLMMessage],
    budget: LLMBudget,
    idempotency_key: str,
    allowed_evidence_ids: set[str],
    allowed_industry_ids: set[str],
    allowed_company_ids: set[str],
) -> ValidatedLLMOutput:
    schema = ModelAnalysisOutput.model_json_schema()
    current_messages = list(messages)
    token_input = 0
    token_output = 0
    estimated_cost = 0.0
    for attempt in (1, 2):
        result = await port.complete_json(
            task="event-impact-analysis" if attempt == 1 else "event-impact-analysis-repair",
            schema=schema,
            messages=current_messages,
            budget=budget,
            idempotency_key=idempotency_key if attempt == 1 else f"{idempotency_key}:repair",
        )
        token_input += result.token_input
        token_output += result.token_output
        estimated_cost += result.estimated_cost
        if estimated_cost > budget.max_cost:
            raise LLMContractError(
                "BUDGET_EXCEEDED",
                "Model result exceeded the per-event budget",
                attempts=attempt,
                token_input=token_input,
                token_output=token_output,
                estimated_cost=estimated_cost,
            )
        try:
            output = _parse_output(result.content)
            _validate_references(
                output,
                allowed_evidence_ids=allowed_evidence_ids,
                allowed_industry_ids=allowed_industry_ids,
                allowed_company_ids=allowed_company_ids,
                attempts=attempt,
                token_input=token_input,
                token_output=token_output,
                estimated_cost=estimated_cost,
            )
        except LLMContractError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            if attempt == 2:
                raise LLMContractError(
                    "LLM_SCHEMA_INVALID",
                    "Model output failed the JSON contract after one repair call",
                    attempts=2,
                    token_input=token_input,
                    token_output=token_output,
                    estimated_cost=estimated_cost,
                ) from exc
            raw = result.content if isinstance(result.content, str) else json.dumps(result.content)
            current_messages.extend(
                [
                    LLMMessage(role="assistant", content=raw[:8_000] or "{}"),
                    LLMMessage(
                        role="user",
                        content=(
                            "Repair the previous output so it exactly matches the supplied JSON Schema. "
                            "Do not add commentary. Validation errors: " + _validation_message(exc)
                        )[:40_000],
                    ),
                ]
            )
            continue
        return ValidatedLLMOutput(
            output=output,
            attempts=attempt,
            token_input=token_input,
            token_output=token_output,
            estimated_cost=estimated_cost,
        )
    raise AssertionError("unreachable")
