from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CompanyImpact, EventCluster, IndustryImpact


@dataclass(frozen=True)
class QualityLabel:
    event_id: str
    cluster_correct: bool
    expected_industry_ids: tuple[str, ...]
    expected_company_ids: tuple[str, ...]


def _id_tuple(value: Any, field: str, line_number: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"Line {line_number}: {field} must be a list of non-empty IDs")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"Line {line_number}: {field} contains duplicate IDs")
    return normalized


def load_quality_labels(path: Path) -> list[QualityLabel]:
    labels: list[QualityLabel] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Line {line_number}: invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Line {line_number}: label must be a JSON object")
            event_id = payload.get("event_id")
            cluster_correct = payload.get("cluster_correct")
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError(f"Line {line_number}: event_id is required")
            event_id = event_id.strip()
            if event_id in seen:
                raise ValueError(f"Line {line_number}: duplicate event_id {event_id}")
            if not isinstance(cluster_correct, bool):
                raise ValueError(f"Line {line_number}: cluster_correct must be boolean")
            labels.append(
                QualityLabel(
                    event_id=event_id,
                    cluster_correct=cluster_correct,
                    expected_industry_ids=_id_tuple(
                        payload.get("expected_industry_ids"),
                        "expected_industry_ids",
                        line_number,
                    ),
                    expected_company_ids=_id_tuple(
                        payload.get("expected_company_ids"),
                        "expected_company_ids",
                        line_number,
                    ),
                )
            )
            seen.add(event_id)
    if not labels:
        raise ValueError("Quality label file is empty")
    return labels


def load_database_predictions(
    session: Session,
    event_ids: list[str],
) -> dict[str, dict[str, list[str]]]:
    event_rows = list(
        session.execute(
            select(EventCluster.id, EventCluster.is_demo).where(EventCluster.id.in_(event_ids))
        )
    )
    found_event_ids = {event_id for event_id, _is_demo in event_rows}
    missing_event_ids = [event_id for event_id in event_ids if event_id not in found_event_ids]
    if missing_event_ids:
        raise ValueError(f"Labeled events do not exist in the database: {missing_event_ids[:10]}")

    demo_event_ids = [event_id for event_id, is_demo in event_rows if is_demo]
    if demo_event_ids:
        raise ValueError(
            f"Demo events are not permitted in the release quality benchmark: {demo_event_ids[:10]}"
        )

    predictions = {event_id: {"industry_ids": [], "company_ids": []} for event_id in event_ids}
    for event_id, industry_id in session.execute(
        select(IndustryImpact.event_id, IndustryImpact.industry_id)
        .where(IndustryImpact.event_id.in_(event_ids))
        .order_by(IndustryImpact.event_id, IndustryImpact.relevance.desc())
    ):
        predictions[event_id]["industry_ids"].append(industry_id)
    for event_id, entity_id in session.execute(
        select(CompanyImpact.event_id, CompanyImpact.entity_id)
        .where(CompanyImpact.event_id.in_(event_ids))
        .order_by(CompanyImpact.event_id, CompanyImpact.relevance.desc())
    ):
        predictions[event_id]["company_ids"].append(entity_id)
    return predictions


def _precision(predicted: list[str], expected: tuple[str, ...], limit: int) -> float:
    selected = predicted[:limit]
    if not selected:
        return 1.0 if not expected else 0.0
    expected_set = set(expected)
    return sum(item in expected_set for item in selected) / len(selected)


def score_quality(
    labels: list[QualityLabel],
    predictions: dict[str, dict[str, list[str]]],
) -> dict[str, float | int]:
    missing = [label.event_id for label in labels if label.event_id not in predictions]
    if missing:
        raise ValueError(f"Predictions are missing labeled events: {missing[:10]}")
    count = len(labels)
    return {
        "event_count": count,
        "cluster_accuracy": sum(label.cluster_correct for label in labels) / count,
        "industry_top3_precision": sum(
            _precision(
                predictions[label.event_id]["industry_ids"],
                label.expected_industry_ids,
                3,
            )
            for label in labels
        )
        / count,
        "company_top5_precision": sum(
            _precision(
                predictions[label.event_id]["company_ids"],
                label.expected_company_ids,
                5,
            )
            for label in labels
        )
        / count,
    }


def quality_gate_failures(
    scores: dict[str, float | int],
    *,
    minimum_events: int = 200,
    cluster_threshold: float = 0.90,
    industry_threshold: float = 0.80,
    company_threshold: float = 0.80,
) -> list[str]:
    failures: list[str] = []
    if scores["event_count"] < minimum_events:
        failures.append(f"event_count {scores['event_count']} is below required {minimum_events}")
    for key, threshold in (
        ("cluster_accuracy", cluster_threshold),
        ("industry_top3_precision", industry_threshold),
        ("company_top5_precision", company_threshold),
    ):
        if scores[key] < threshold:
            failures.append(f"{key} {scores[key]:.3f} is below required {threshold:.3f}")
    return failures
