from datetime import UTC, datetime

import pytest
from news_claws.schemas import (
    Confidence,
    Direction,
    ImpactContract,
    ReportContract,
    SourceLink,
    Strength,
    VerificationContract,
    VerificationStatus,
    validate_evidence_whitelist,
)


def report(evidence_id: str = "ev_1") -> ReportContract:
    now = datetime.now(UTC)
    return ReportContract(
        event_id="evt_1",
        report_version=1,
        headline="Test event",
        summary=["A traceable summary"],
        overall_tone="neutral",
        verification=VerificationContract(
            status=VerificationStatus.SINGLE_SOURCE_REPORTED,
            confidence=Confidence.MEDIUM,
            claim_ids=["clm_1"],
            supporting_evidence_ids=["ev_1"],
            conflicting_evidence_ids=[],
            rationale="One information chain.",
        ),
        industries=[
            ImpactContract(
                target_id="industry_1",
                target_name="Industry",
                relevance=70,
                direction=Direction.NEUTRAL,
                strength=Strength.LOW,
                horizon="weeks",
                mechanism="unknown",
                explanation="No causal direction is established.",
                confidence=Confidence.LOW,
                evidence_ids=[evidence_id],
            )
        ],
        companies=[],
        source_links=[
            SourceLink(
                article_id="art_1",
                source_name="Source",
                url="https://example.com/story",
                title="Story",
                published_at=now,
                independence_group="source_1",
            )
        ],
        generated_at=now,
        data_cutoff_at=now,
        model="rules-v1",
        prompt_version="v1",
        disclaimer="Not advice.",
    )


def test_server_evidence_whitelist_accepts_supplied_ids() -> None:
    validate_evidence_whitelist(report(), {"ev_1"})


def test_server_evidence_whitelist_rejects_model_invented_ids() -> None:
    with pytest.raises(ValueError, match="EVIDENCE_ID_INVALID"):
        validate_evidence_whitelist(report("ev_invented"), {"ev_1"})
