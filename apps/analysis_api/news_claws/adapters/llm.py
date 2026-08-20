from __future__ import annotations

import json
import math
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from news_claws.domain.llm import LLMBudget, LLMMessage, LLMResult


class LLMProviderError(RuntimeError):
    pass


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        input_cost_per_million: float = 0.0,
        output_cost_per_million: float = 0.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("LLM_API_BASE_URL must be an absolute HTTP(S) URL")
        if parts.username or parts.password:
            raise ValueError("LLM_API_BASE_URL must not contain credentials")
        if not api_key:
            raise ValueError("LLM_API_KEY is required for an OpenAI-compatible provider")
        if not model:
            raise ValueError("LLM_MODEL is required for an OpenAI-compatible provider")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("LLM timeout must be a positive finite number")
        self.endpoint = urljoin(base_url.rstrip("/") + "/", "chat/completions")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        if (
            not all(
                math.isfinite(value) for value in (input_cost_per_million, output_cost_per_million)
            )
            or input_cost_per_million < 0
            or output_cost_per_million < 0
        ):
            raise ValueError("LLM token prices must be finite and non-negative")
        self.input_cost_per_million = input_cost_per_million
        self.output_cost_per_million = output_cost_per_million
        self.transport = transport

    async def complete_json(
        self,
        task: str,
        schema: dict[str, Any],
        messages: list[LLMMessage],
        budget: LLMBudget,
        idempotency_key: str,
    ) -> LLMResult:
        schema_name = re.sub(r"[^a-zA-Z0-9_-]", "_", task)[:64] or "structured_output"
        payload = {
            "model": self.model,
            "messages": [message.model_dump() for message in messages],
            "temperature": 0,
            "max_completion_tokens": budget.max_output_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            transport=self.transport,
            trust_env=False,
        ) as client:
            response = await client.post(self.endpoint, headers=headers, json=payload)
        response.raise_for_status()
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            refusal = message.get("refusal")
            content = message.get("content")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(
                "LLM response does not match the Chat Completions contract"
            ) from exc
        if refusal:
            raise LLMProviderError("LLM refused the structured analysis request")
        if not isinstance(content, (str, dict)):
            raise LLMProviderError("LLM response content must be a JSON string or object")
        usage = body.get("usage") or {}
        try:
            token_input = int(usage.get("prompt_tokens") or 0)
            token_output = int(usage.get("completion_tokens") or 0)
            provider_cost = body.get("estimated_cost")
            estimated_cost = (
                float(provider_cost)
                if provider_cost is not None
                else (
                    token_input * self.input_cost_per_million
                    + token_output * self.output_cost_per_million
                )
                / 1_000_000
            )
            return LLMResult(
                content=content,
                token_input=token_input,
                token_output=token_output,
                estimated_cost=estimated_cost,
            )
        except (TypeError, ValueError) as exc:
            raise LLMProviderError("LLM usage metadata is invalid") from exc


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
