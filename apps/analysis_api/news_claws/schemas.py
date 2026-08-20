from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VerificationStatus(StrEnum):
    PRIMARY_SOURCE_CONFIRMED = "primary_source_confirmed"
    MULTI_SOURCE_CORROBORATED = "multi_source_corroborated"
    SINGLE_SOURCE_REPORTED = "single_source_reported"
    DISPUTED = "disputed"
    WITHDRAWN_OR_DISPROVED = "withdrawn_or_disproved"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Direction(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class Strength(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceCreate(StrictModel):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,79}$")]
    name: Annotated[str, Field(min_length=2, max_length=240)]
    owner: Annotated[str, Field(min_length=2, max_length=240)]
    region: Annotated[str, Field(min_length=2, max_length=32)]
    language: Annotated[str, Field(min_length=2, max_length=16)]
    source_type: str = "government"
    tier: Literal["S1", "S2", "S3", "S4"]
    official: bool = False
    method: Literal["rss", "atom", "api", "sitemap", "manual", "fixture"]
    entry_url: str
    fallback_url: str | None = None
    schedule: str = "*/15 * * * *"
    timezone: str = "UTC"
    content_policy: Literal["metadata_only", "metadata_and_excerpt", "fulltext_allowed"]
    compliance_notes: str = ""
    contact_owner: str = "source-admin"
    enabled: bool = True
    is_demo: bool = False


class SourceUpdate(StrictModel):
    name: Annotated[str, Field(min_length=2, max_length=240)] | None = None
    owner: Annotated[str, Field(min_length=2, max_length=240)] | None = None
    region: Annotated[str, Field(min_length=2, max_length=32)] | None = None
    language: Annotated[str, Field(min_length=2, max_length=16)] | None = None
    source_type: str | None = None
    tier: Literal["S1", "S2", "S3", "S4"] | None = None
    official: bool | None = None
    method: Literal["rss", "atom", "api", "sitemap", "manual"] | None = None
    entry_url: str | None = None
    fallback_url: str | None = None
    schedule: str | None = None
    timezone: str | None = None
    content_policy: Literal["metadata_only", "metadata_and_excerpt", "fulltext_allowed"] | None = (
        None
    )
    compliance_notes: str | None = None
    contact_owner: str | None = None
    enabled: bool | None = None


class IngestionRequest(StrictModel):
    source_ids: list[str] = Field(default_factory=list, max_length=60)
    max_items_per_source: int = Field(default=20, ge=1, le=100)


class ManualIngestionRequest(StrictModel):
    source_id: Annotated[str, Field(min_length=3, max_length=80)]
    url: Annotated[str, Field(min_length=10, max_length=2048)]


EmailAddress = Annotated[
    str,
    Field(
        min_length=5,
        max_length=320,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]


class SubscriptionCreate(StrictModel):
    email: EmailAddress
    company_ids: list[str] = Field(default_factory=list, max_length=100)
    industry_ids: list[str] = Field(default_factory=list, max_length=100)
    min_relevance: int = Field(default=70, ge=0, le=100)
    frequency: Literal["immediate", "daily"] = "daily"
    digest_hour_utc: int = Field(default=0, ge=0, le=23)
    enabled: bool = True


class SubscriptionUpdate(StrictModel):
    email: EmailAddress | None = None
    company_ids: list[str] | None = Field(default=None, max_length=100)
    industry_ids: list[str] | None = Field(default=None, max_length=100)
    min_relevance: int | None = Field(default=None, ge=0, le=100)
    frequency: Literal["immediate", "daily"] | None = None
    digest_hour_utc: int | None = Field(default=None, ge=0, le=23)
    enabled: bool | None = None


class FeedbackCreate(StrictModel):
    target_type: Literal["event", "cluster", "evidence", "industry", "company"]
    target_id: Annotated[str, Field(min_length=3, max_length=80)]
    verdict: Literal["correct", "incorrect", "uncertain"]
    reason: Annotated[str, Field(min_length=3, max_length=2000)]
    actor: Annotated[str, Field(min_length=2, max_length=120)] = "local-analyst"


class ReanalyzeRequest(StrictModel):
    stages: list[Literal["verify", "impact", "report"]] = Field(
        default_factory=lambda: ["verify", "impact", "report"]
    )
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class MergeEventsRequest(StrictModel):
    event_ids: list[str] = Field(min_length=2, max_length=20)
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class SplitEventRequest(StrictModel):
    article_ids: list[str] = Field(min_length=1, max_length=100)
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class ClaimContract(StrictModel):
    claim_id: str
    text: str
    subject: str | None
    predicate: str | None
    object: str | None
    claim_time: datetime | None
    location: str | None
    kind: Literal["fact", "forecast", "opinion", "unverifiable"]
    source_quote: str
    article_id: str


class ImpactContract(StrictModel):
    target_id: str
    target_name: str
    role: str | None = None
    relevance: int = Field(ge=0, le=100)
    direction: Direction
    strength: Strength
    horizon: Literal["days", "weeks", "quarters", "structural"]
    mechanism: Literal[
        "demand",
        "supply",
        "cost",
        "regulation",
        "financing",
        "competition",
        "reputation",
        "operations",
        "geopolitical",
        "unknown",
    ]
    explanation: str
    confidence: Confidence
    evidence_ids: list[str] = Field(min_length=1)


class VerificationContract(StrictModel):
    status: VerificationStatus
    confidence: Confidence
    claim_ids: list[str]
    supporting_evidence_ids: list[str]
    conflicting_evidence_ids: list[str]
    rationale: str


class SourceLink(StrictModel):
    article_id: str
    source_name: str
    url: str
    title: str
    published_at: datetime | None
    independence_group: str


class ReportContract(StrictModel):
    event_id: str
    report_version: int = Field(ge=1)
    headline: str
    summary: list[str] = Field(min_length=1, max_length=5)
    overall_tone: Literal["positive", "negative", "neutral", "mixed", "not_applicable"]
    verification: VerificationContract
    industries: list[ImpactContract] = Field(max_length=3)
    companies: list[ImpactContract] = Field(max_length=5)
    source_links: list[SourceLink] = Field(min_length=1)
    generated_at: datetime
    data_cutoff_at: datetime
    model: str
    prompt_version: str
    disclaimer: str

    @model_validator(mode="after")
    def evidence_ids_must_exist_in_sources(self) -> ReportContract:
        # Membership in the server-selected whitelist is checked by the report service.
        impact_ids = [eid for item in self.industries + self.companies for eid in item.evidence_ids]
        if len(impact_ids) != len([eid for eid in impact_ids if eid]):
            raise ValueError("Impact evidence_ids cannot be blank")
        return self


def validate_evidence_whitelist(report: ReportContract, allowed_ids: set[str]) -> None:
    referenced = set(report.verification.supporting_evidence_ids)
    referenced.update(report.verification.conflicting_evidence_ids)
    for impact in report.industries + report.companies:
        referenced.update(impact.evidence_ids)
    unknown = referenced - allowed_ids
    if unknown:
        raise ValueError(f"EVIDENCE_ID_INVALID: {sorted(unknown)}")
