from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "source"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    owner: Mapped[str] = mapped_column(String(240))
    region: Mapped[str] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(16), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="government")
    tier: Mapped[str] = mapped_column(String(8), index=True)
    official: Mapped[bool] = mapped_column(Boolean, default=False)
    method: Mapped[str] = mapped_column(String(32))
    entry_url: Mapped[str] = mapped_column(Text)
    fallback_url: Mapped[str | None] = mapped_column(Text)
    schedule: Mapped[str] = mapped_column(String(80), default="*/15 * * * *")
    timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    content_policy: Mapped[str] = mapped_column(String(40), default="metadata_and_excerpt")
    parser: Mapped[str] = mapped_column(String(32), default="auto")
    compliance_notes: Mapped[str] = mapped_column(Text, default="")
    contact_owner: Mapped[str] = mapped_column(String(120), default="source-admin")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SourceRun(Base):
    __tablename__ = "source_run"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("run"))
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)


class Article(Base):
    __tablename__ = "article"
    __table_args__ = (
        UniqueConstraint("source_id", "canonical_url", name="uq_article_source_url"),
        Index("ix_article_content_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    source_id: Mapped[str] = mapped_column(ForeignKey("source.id", ondelete="RESTRICT"), index=True)
    canonical_url: Mapped[str] = mapped_column(Text)
    original_url: Mapped[str] = mapped_column(Text)
    origin_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(240))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_timezone: Mapped[str] = mapped_column(String(80), default="UTC")
    language: Mapped[str] = mapped_column(String(16), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    independence_group: Mapped[str] = mapped_column(String(80), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    versions: Mapped[list[ArticleVersion]] = relationship(
        back_populates="article", cascade="all, delete-orphan", order_by="ArticleVersion.fetched_at"
    )


class ArticleVersion(Base):
    __tablename__ = "article_version"
    __table_args__ = (
        UniqueConstraint("article_id", "version_hash", name="uq_article_version_hash"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ver"))
    article_id: Mapped[str] = mapped_column(
        ForeignKey("article.id", ondelete="CASCADE"), index=True
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    body_excerpt: Mapped[str] = mapped_column(Text, default="")
    body_ref: Mapped[str | None] = mapped_column(Text)
    body_permitted: Mapped[bool] = mapped_column(Boolean, default=False)
    version_hash: Mapped[str] = mapped_column(String(64))
    parse_diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    article: Mapped[Article] = relationship(back_populates="versions")


class SyndicationLink(Base):
    __tablename__ = "syndication_link"
    __table_args__ = (
        UniqueConstraint("from_article_id", "to_article_id", name="uq_syndication_pair"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("syn"))
    from_article_id: Mapped[str] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"))
    to_article_id: Mapped[str] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"))
    relation: Mapped[str] = mapped_column(String(24), default="repost")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    rationale: Mapped[str] = mapped_column(Text)


class EventCluster(Base):
    __tablename__ = "event_cluster"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("evt"))
    representative_article_id: Mapped[str | None] = mapped_column(
        ForeignKey("article.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    state: Mapped[str] = mapped_column(String(24), default="active", index=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class EventArticle(Base):
    __tablename__ = "event_article"

    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_cluster.id", ondelete="CASCADE"), primary_key=True
    )
    article_id: Mapped[str] = mapped_column(
        ForeignKey("article.id", ondelete="CASCADE"), primary_key=True
    )
    similarity: Mapped[float] = mapped_column(Float, default=1.0)
    is_representative: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by: Mapped[str] = mapped_column(String(24), default="algorithm")


class AnalysisRun(Base):
    __tablename__ = "analysis_run"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ana"))
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_cluster.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(120))
    prompt_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(32), default="1")
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    output_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="succeeded")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Claim(Base):
    __tablename__ = "claim"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("clm"))
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_cluster.id", ondelete="CASCADE"), index=True
    )
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"))
    text: Mapped[str] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(240))
    predicate: Mapped[str | None] = mapped_column(String(120))
    object: Mapped[str | None] = mapped_column(Text)
    claim_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[str | None] = mapped_column(String(40))
    quote: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24), default="fact")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ev"))
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"), index=True)
    article_id: Mapped[str] = mapped_column(
        ForeignKey("article.id", ondelete="RESTRICT"), index=True
    )
    source_tier: Mapped[str] = mapped_column(String(8))
    stance: Mapped[str] = mapped_column(String(24), default="supports")
    quote: Mapped[str] = mapped_column(Text)
    independence_group: Mapped[str] = mapped_column(String(80), index=True)
    independence_known: Mapped[bool] = mapped_column(Boolean, default=True)
    quality: Mapped[str] = mapped_column(String(16), default="medium")
    primary_material: Mapped[bool] = mapped_column(Boolean, default=False)
    directly_observed: Mapped[bool] = mapped_column(Boolean, default=False)
    query: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Verification(Base):
    __tablename__ = "verification"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("vf"))
    claim_id: Mapped[str] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(48), index=True)
    confidence: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Industry(Base):
    __tablename__ = "industry"
    __table_args__ = (UniqueConstraint("scheme", "code", name="uq_industry_scheme_code"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    scheme: Mapped[str] = mapped_column(String(32), default="ISIC-derived")
    code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(160), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("industry.id", ondelete="SET NULL"))
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)


class Entity(Base):
    __tablename__ = "entity"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(24), default="company")
    canonical_name: Mapped[str] = mapped_column(String(240), index=True)
    country: Mapped[str | None] = mapped_column(String(40))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("entity.id", ondelete="SET NULL"))
    identifiers_json: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    industry_id: Mapped[str | None] = mapped_column(ForeignKey("industry.id", ondelete="SET NULL"))


class EntityAlias(Base):
    __tablename__ = "entity_alias"
    __table_args__ = (UniqueConstraint("entity_id", "alias", name="uq_entity_alias"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("als"))
    entity_id: Mapped[str] = mapped_column(ForeignKey("entity.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(240), index=True)
    language: Mapped[str] = mapped_column(String(16), default="und")
    alias_type: Mapped[str] = mapped_column(String(24), default="name")
    negative: Mapped[bool] = mapped_column(Boolean, default=False)


class IndustryImpact(Base):
    __tablename__ = "industry_impact"
    __table_args__ = (UniqueConstraint("event_id", "industry_id", name="uq_event_industry"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ii"))
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_cluster.id", ondelete="CASCADE"), index=True
    )
    industry_id: Mapped[str] = mapped_column(ForeignKey("industry.id", ondelete="RESTRICT"))
    relevance: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(16))
    strength: Mapped[str] = mapped_column(String(16))
    horizon: Mapped[str] = mapped_column(String(24))
    mechanism: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"))


class CompanyImpact(Base):
    __tablename__ = "company_impact"
    __table_args__ = (UniqueConstraint("event_id", "entity_id", name="uq_event_company"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ci"))
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_cluster.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[str] = mapped_column(ForeignKey("entity.id", ondelete="RESTRICT"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    relevance: Mapped[int] = mapped_column(Integer)
    direction: Mapped[str] = mapped_column(String(16))
    strength: Mapped[str] = mapped_column(String(16))
    horizon: Mapped[str] = mapped_column(String(24))
    mechanism: Mapped[str] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String(16))
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    analysis_run_id: Mapped[str] = mapped_column(ForeignKey("analysis_run.id", ondelete="RESTRICT"))


class Report(Base):
    __tablename__ = "report"
    __table_args__ = (UniqueConstraint("event_id", "version", name="uq_report_event_version"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rpt"))
    event_id: Mapped[str] = mapped_column(
        ForeignKey("event_cluster.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    artifact_ref: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_markdown: Mapped[str] = mapped_column(Text)
    content_html: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fb"))
    target_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[str] = mapped_column(String(80), index=True)
    verdict: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(120))
    analysis_version: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineJob(Base):
    __tablename__ = "pipeline_job"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    job_type: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aud"))
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="anonymous", index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    method: Mapped[str] = mapped_column(String(12))
    path: Mapped[str] = mapped_column(String(500))
    status_code: Mapped[int] = mapped_column(Integer)
    client_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class Subscription(Base):
    __tablename__ = "subscription"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sub"))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    company_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    industry_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    min_relevance: Mapped[int] = mapped_column(Integer, default=70)
    frequency: Mapped[str] = mapped_column(String(24), default="daily")
    digest_hour_utc: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ntf"))
    report_id: Mapped[str] = mapped_column(ForeignKey("report.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(24))
    target_hash: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
