from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .adapters.http_sources import (
    discover_site_entries,
    fetch_api_entries,
    fetch_html_entry,
    fetch_sitemap_entries,
)
from .adapters.llm import LLMProviderError, OpenAICompatibleLLM, compact_json
from .adapters.rss import fetch_feed
from .catalog import load_yaml
from .config import Settings
from .domain.llm import (
    LLMBudget,
    LLMContractError,
    LLMMessage,
    LLMPort,
    ValidatedLLMOutput,
    complete_model_analysis,
)
from .domain.normalization import canonicalize_url, content_hash, jaccard_similarity, normalize_text
from .domain.security import UnsafeUrlError
from .domain.verification import EvidenceFact, decide_verification
from .models import (
    AnalysisRun,
    Article,
    ArticleVersion,
    Claim,
    CompanyImpact,
    Entity,
    EntityAlias,
    EventArticle,
    EventCluster,
    Evidence,
    Feedback,
    Industry,
    IndustryImpact,
    PipelineJob,
    Report,
    Source,
    SourceRun,
    SyndicationLink,
    Verification,
    utcnow,
)
from .notifications import queue_report_notifications
from .reporting import persist_report
from .schemas import FeedbackCreate, SourceCreate, SourceUpdate

POSITIVE_TERMS = {
    "增加",
    "增长",
    "扩容",
    "批准",
    "改善",
    "机会",
    "支持",
    "投资",
    "提升",
    "gain",
    "growth",
    "approve",
    "support",
    "investment",
    "increase",
}
NEGATIVE_TERMS = {
    "下降",
    "减少",
    "禁止",
    "调查",
    "罚款",
    "成本",
    "压力",
    "风险",
    "撤回",
    "否认",
    "decline",
    "ban",
    "investigation",
    "fine",
    "cost",
    "risk",
    "withdraw",
}

MECHANISM_LABELS = {
    "demand": "需求",
    "supply": "供给",
    "cost": "成本",
    "regulation": "监管",
    "financing": "融资",
    "competition": "竞争",
    "reputation": "声誉",
    "operations": "经营",
    "geopolitical": "地缘政治",
    "unknown": "未知",
}

LIVE_CLUSTER_SIMILARITY_THRESHOLD = 0.72
DEMO_CLUSTER_SIMILARITY_THRESHOLD = 0.20
CLUSTER_WINDOW_DAYS = 7
MAX_LLM_EVIDENCE = 12
MAX_LLM_INDUSTRIES = 24
MAX_LLM_COMPANIES = 12
MAX_LLM_ALIASES = 3
MAX_LLM_KEYWORDS_PER_INDUSTRY = 6
MAX_LLM_KEYWORD_CHARS = 48
MAX_LLM_EVIDENCE_QUOTE_CHARS = 320
MAX_LLM_TARGET_NAME_CHARS = 160
MAX_LLM_ALIAS_CHARS = 80
MAX_LLM_EVENT_TEXT_CHARS = 6_000


@dataclass(frozen=True)
class PreparedAnalysis:
    event_id: str
    input_hash: str
    combined_text: str
    evidence_ids: tuple[str, ...]
    verification_id: str
    impact_run_id: str


@dataclass(frozen=True)
class LLMPromptContext:
    messages: tuple[LLMMessage, ...]
    evidence_ids: frozenset[str]
    industry_ids: frozenset[str]
    company_ids: frozenset[str]


@dataclass(frozen=True)
class EventMutationResult:
    event_id: str
    analysis_status: str
    analysis_error: str | None


def _ensure_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _ensure_utc(parsed)


def _latest_version(session: Session, article_id: str) -> ArticleVersion | None:
    return session.scalar(
        select(ArticleVersion)
        .where(ArticleVersion.article_id == article_id)
        .order_by(ArticleVersion.fetched_at.desc())
    )


def _event_input_hash(session: Session, event_id: str) -> str:
    rows = session.execute(
        select(Article.id, ArticleVersion.version_hash)
        .join(EventArticle, EventArticle.article_id == Article.id)
        .join(ArticleVersion, ArticleVersion.article_id == Article.id)
        .where(EventArticle.event_id == event_id)
        .order_by(Article.id, ArticleVersion.fetched_at.desc())
    ).all()
    latest_by_article: dict[str, str] = {}
    for article_id, version_hash in rows:
        latest_by_article.setdefault(article_id, version_hash)
    value = json.dumps(sorted(latest_by_article.items()), separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _analysis_input_hash(session: Session, event_id: str, settings: Settings) -> str:
    source_hash = _event_input_hash(session, event_id)
    analysis_version = (
        "deterministic-v1" if settings.llm_provider == "deterministic" else "structured-impact-v1"
    )
    value = ":".join([source_hash, settings.llm_provider, settings.llm_model, analysis_version])
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_source(session: Session, payload: SourceCreate) -> Source:
    if session.get(Source, payload.id):
        raise ValueError(f"Source already exists: {payload.id}")
    source = Source(**payload.model_dump())
    session.add(source)
    session.commit()
    return source


def update_source(session: Session, source: Source, payload: SourceUpdate) -> Source:
    if source.is_demo:
        raise ValueError("Demo sources are managed by the bundled catalog")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValueError("At least one source field must be provided")
    proposed_method = changes.get("method", source.method)
    proposed_parser = changes.get("parser", source.parser)
    proposed_policy = changes.get("content_policy", source.content_policy)
    if proposed_method == "website" and proposed_parser != "news-please":
        raise ValueError("website sources require parser=news-please")
    if proposed_method == "website" and proposed_policy == "metadata_only":
        raise ValueError("website sources require an excerpt-enabled content policy")
    for key, value in changes.items():
        setattr(source, key, value)
    session.commit()
    return source


def _find_cluster(
    session: Session,
    title: str,
    published_at: datetime | None,
    *,
    is_demo: bool,
) -> tuple[EventCluster | None, float]:
    article_time = published_at or utcnow()
    window_start = article_time - timedelta(days=CLUSTER_WINDOW_DAYS)
    window_end = article_time + timedelta(days=CLUSTER_WINDOW_DAYS)
    candidates = session.scalars(
        select(EventCluster)
        .where(
            EventCluster.last_seen >= window_start,
            EventCluster.last_seen <= window_end,
            EventCluster.state == "active",
            EventCluster.locked.is_(False),
            EventCluster.is_demo.is_(is_demo),
        )
        .order_by(EventCluster.last_seen.desc())
        .limit(200)
    )
    best: EventCluster | None = None
    best_score = 0.0
    for event in candidates:
        score = jaccard_similarity(title, event.title)
        if score > best_score:
            best, best_score = event, score
    threshold = DEMO_CLUSTER_SIMILARITY_THRESHOLD if is_demo else LIVE_CLUSTER_SIMILARITY_THRESHOLD
    return (best, best_score) if best_score >= threshold else (None, best_score)


def _assign_independence_group(
    session: Session,
    *,
    source: Source,
    origin_url: str | None,
    article_hash: str,
) -> tuple[str, Article | None, str]:
    if origin_url:
        group = "chain_" + hashlib.sha256(canonicalize_url(origin_url).encode()).hexdigest()[:16]
        prior = session.scalar(select(Article).where(Article.independence_group == group))
        return group, prior, "shared declared origin URL"
    prior = session.scalar(
        select(Article).where(Article.content_hash == article_hash).order_by(Article.first_seen_at)
    )
    if prior:
        return prior.independence_group, prior, "exact normalized content hash"
    return f"publisher_{source.id}", None, "publisher/editorial chain"


def ingest_article(
    session: Session,
    source: Source,
    payload: dict[str, Any],
) -> tuple[Article, EventCluster, bool]:
    title = normalize_text(payload.get("title"))
    if not title:
        raise ValueError("Article title is required")
    original_url = payload.get("url") or payload.get("original_url")
    if not original_url:
        raise ValueError("Article URL is required")
    canonical_url = canonicalize_url(original_url)
    summary = normalize_text(payload.get("summary"))
    body_excerpt = normalize_text(payload.get("body_excerpt"))[:2000]
    article_hash = content_hash(title, body_excerpt or summary)
    version_hash = content_hash(title, summary, body_excerpt, payload.get("status"))
    published_at = _parse_datetime(payload.get("published_at"))
    updated_at = _parse_datetime(payload.get("updated_at"))
    origin_url = payload.get("origin_url")
    article = session.scalar(
        select(Article).where(
            Article.source_id == source.id, Article.canonical_url == canonical_url
        )
    )
    created = article is None
    prior_for_syndication: Article | None = None
    rationale = ""
    if article is None:
        group, prior_for_syndication, rationale = _assign_independence_group(
            session,
            source=source,
            origin_url=origin_url,
            article_hash=article_hash,
        )
        article = Article(
            source_id=source.id,
            canonical_url=canonical_url,
            original_url=original_url,
            origin_url=origin_url,
            title=title,
            author=payload.get("author"),
            published_at=published_at,
            updated_at=updated_at,
            original_timezone=payload.get("timezone", source.timezone),
            language=payload.get("language", source.language),
            content_hash=article_hash,
            independence_group=group,
        )
        session.add(article)
        session.flush()
        if prior_for_syndication and prior_for_syndication.id != article.id:
            session.add(
                SyndicationLink(
                    from_article_id=article.id,
                    to_article_id=prior_for_syndication.id,
                    relation="repost",
                    confidence=1.0,
                    rationale=rationale,
                )
            )
    else:
        article.last_seen_at = utcnow()
        article.title = title
        article.updated_at = updated_at or article.updated_at
        article.content_hash = article_hash

    existing_version = session.scalar(
        select(ArticleVersion).where(
            ArticleVersion.article_id == article.id, ArticleVersion.version_hash == version_hash
        )
    )
    if existing_version is None:
        session.add(
            ArticleVersion(
                article_id=article.id,
                title=title,
                summary=summary,
                body_excerpt=body_excerpt,
                body_ref=payload.get("body_ref"),
                body_permitted=source.content_policy == "fulltext_allowed",
                version_hash=version_hash,
                parse_diagnostics=payload.get("parse_diagnostics", {}),
            )
        )

    membership = session.scalar(select(EventArticle).where(EventArticle.article_id == article.id))
    if membership:
        event = session.get(EventCluster, membership.event_id)
        assert event is not None
    else:
        event, score = _find_cluster(session, title, published_at, is_demo=source.is_demo)
        if event is None:
            event = EventCluster(
                title=title,
                representative_article_id=article.id,
                first_seen=published_at or utcnow(),
                last_seen=published_at or utcnow(),
                is_demo=source.is_demo,
            )
            session.add(event)
            session.flush()
            score = 1.0
        else:
            event.last_seen = max(_ensure_utc(event.last_seen), published_at or utcnow())
            event.is_demo = event.is_demo and source.is_demo
        session.add(
            EventArticle(
                event_id=event.id,
                article_id=article.id,
                similarity=score,
                is_representative=event.representative_article_id == article.id,
            )
        )
    session.flush()
    return article, event, created


def _impact_direction(text: str, *, industry_id: str | None = None) -> tuple[str, str, str]:
    positive = sum(1 for term in POSITIVE_TERMS if term in text)
    negative = sum(1 for term in NEGATIVE_TERMS if term in text)
    regulation_context = any(term in text for term in {"审查", "监管", "合规", "regulation"})
    if regulation_context and industry_id == "isic_6209":
        return "positive", "regulation", "weeks"
    if regulation_context and industry_id == "isic_6201":
        return "negative", "cost", "quarters"
    if positive and negative:
        return "mixed", "operations", "quarters"
    if positive:
        mechanism = (
            "demand" if any(term in text for term in {"需求", "扩容", "投资"}) else "operations"
        )
        return "positive", mechanism, "quarters"
    if negative:
        mechanism = "cost" if "成本" in text else "regulation"
        return "negative", mechanism, "weeks"
    return "neutral", "unknown", "weeks"


def _alias_matches(text: str, alias: EntityAlias) -> bool:
    candidate = normalize_text(alias.alias)
    if not candidate:
        return False
    if alias.alias_type != "ticker":
        return candidate.casefold() in text.casefold()

    ticker = candidate.upper()
    if len(ticker) == 1:
        tokens = ("$" + ticker, "(" + ticker + ")")
        return any(
            re.search(rf"(?<![A-Z0-9]){re.escape(token)}(?![A-Z0-9])", text) is not None
            for token in tokens
        )
    return re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", text) is not None


def _prepare_event_analysis(
    session: Session,
    event_id: str,
    settings: Settings,
    *,
    input_hash: str,
) -> PreparedAnalysis:
    event = session.get(EventCluster, event_id)
    if event is None:
        raise LookupError(f"Event not found: {event_id}")
    rows = session.execute(
        select(Article, Source)
        .join(EventArticle, EventArticle.article_id == Article.id)
        .join(Source, Source.id == Article.source_id)
        .where(EventArticle.event_id == event_id)
        .order_by(Source.official.desc(), Article.published_at)
    ).all()
    if not rows:
        raise ValueError("Cannot analyze an event with no articles")
    versions = {article.id: _latest_version(session, article.id) for article, _source in rows}
    session.execute(
        update(Claim)
        .where(Claim.event_id == event_id, Claim.is_current.is_(True))
        .values(is_current=False)
    )
    representative, representative_source = rows[0]
    event.representative_article_id = representative.id
    event.title = representative.title
    run = AnalysisRun(
        event_id=event_id,
        stage="verify",
        model=settings.llm_model,
        prompt_version="deterministic-evidence-v1",
        schema_version="1",
        input_hash=input_hash,
        output_json={},
    )
    session.add(run)
    session.flush()
    representative_version = versions[representative.id]
    claim = Claim(
        event_id=event_id,
        analysis_run_id=run.id,
        text=representative.title,
        subject=representative_source.owner,
        predicate="published" if representative_source.official else "reported",
        object=representative.title,
        claim_time=representative.published_at,
        location=representative_source.region,
        quote=(representative_version.summary if representative_version else "")
        or representative.title,
        kind="fact",
    )
    session.add(claim)
    session.flush()

    evidence_rows: list[Evidence] = []
    for article, source in rows:
        version = versions[article.id]
        combined = normalize_text(
            " ".join(
                [
                    article.title,
                    version.summary if version else "",
                    version.body_excerpt if version else "",
                ]
            )
        )
        if any(term in combined for term in {"正式撤回", "withdrawn"}):
            stance = "withdrawn"
        elif any(term in combined for term in {"否认该事件", "直接否定", "disproves"}):
            stance = "conflicts"
        else:
            stance = "supports"
        evidence_item = Evidence(
            claim_id=claim.id,
            article_id=article.id,
            source_tier=source.tier,
            stance=stance,
            quote=((version.summary if version else "") or article.title)[:500],
            independence_group=article.independence_group,
            independence_known=not article.independence_group.startswith("unknown_"),
            quality="high" if source.tier in {"S1", "S2"} else "medium",
            primary_material=source.tier == "S1" and source.official,
            directly_observed=source.official and article.id == representative.id,
        )
        session.add(evidence_item)
        evidence_rows.append(evidence_item)
    session.flush()
    decision = decide_verification(
        [
            EvidenceFact(
                evidence_id=item.id,
                stance=item.stance,
                independence_group=item.independence_group,
                independence_known=item.independence_known,
                quality=item.quality,
                primary_material=item.primary_material,
                directly_observed=item.directly_observed,
            )
            for item in evidence_rows
        ]
    )
    verification = Verification(
        claim_id=claim.id,
        status=decision.status.value,
        confidence=decision.confidence.value,
        rationale=decision.rationale,
        analysis_run_id=run.id,
    )
    session.add(verification)
    run.output_json = {
        "claim_id": claim.id,
        "verification_status": decision.status.value,
        "supporting_evidence_ids": decision.supporting_ids,
        "conflicting_evidence_ids": decision.conflicting_ids,
    }

    session.execute(delete(IndustryImpact).where(IndustryImpact.event_id == event_id))
    session.execute(delete(CompanyImpact).where(CompanyImpact.event_id == event_id))
    impact_run = AnalysisRun(
        event_id=event_id,
        stage="impact",
        model=settings.llm_model,
        prompt_version="deterministic-impact-v1",
        schema_version="1",
        input_hash=input_hash,
        output_json={},
    )
    session.add(impact_run)
    session.flush()
    combined_text_original = normalize_text(
        " ".join(
            article.title
            + " "
            + ((versions[article.id].summary if versions[article.id] else "") or "")
            + " "
            + ((versions[article.id].body_excerpt if versions[article.id] else "") or "")
            for article, _source in rows
        )
    )
    combined_text = combined_text_original.lower()
    default_evidence_ids = [item.id for item in evidence_rows[:3]]
    industry_scores: dict[str, int] = {}
    for industry in session.scalars(select(Industry)):
        hits = sum(1 for keyword in industry.keywords if keyword.lower() in combined_text)
        if hits:
            industry_scores[industry.id] = min(95, 55 + hits * 12)
    for industry_id, relevance in sorted(
        industry_scores.items(), key=lambda item: item[1], reverse=True
    )[:3]:
        industry = session.get(Industry, industry_id)
        assert industry is not None
        direction, mechanism, horizon = _impact_direction(combined_text, industry_id=industry_id)
        strength = "high" if relevance >= 85 else "medium" if relevance >= 65 else "low"
        session.add(
            IndustryImpact(
                event_id=event_id,
                industry_id=industry_id,
                relevance=relevance,
                direction=direction,
                strength=strength,
                horizon=horizon,
                mechanism=mechanism,
                explanation=f"事件文本直接命中 {industry.name} 的受控关键词；潜在影响通过 {MECHANISM_LABELS.get(mechanism, mechanism)}机制传导。",
                confidence="high" if relevance >= 85 else "medium",
                evidence_ids=default_evidence_ids,
                analysis_run_id=impact_run.id,
            )
        )

    companies_added: list[dict[str, Any]] = []
    for entity in session.scalars(select(Entity).where(Entity.entity_type == "company")):
        aliases = list(
            session.scalars(
                select(EntityAlias).where(
                    EntityAlias.entity_id == entity.id, EntityAlias.negative.is_(False)
                )
            )
        )
        direct_aliases = [
            alias.alias for alias in aliases if _alias_matches(combined_text_original, alias)
        ]
        indirect = entity.industry_id in industry_scores
        if not direct_aliases and not indirect:
            continue
        relevance = (
            92 if direct_aliases else min(72, industry_scores.get(entity.industry_id or "", 0))
        )
        direction, mechanism, horizon = _impact_direction(
            combined_text, industry_id=entity.industry_id
        )
        role = (
            "regulatory_target"
            if "审查" in combined_text and entity.industry_id == "isic_6201"
            else "subject"
        )
        if entity.industry_id == "isic_6209" and "审查" in combined_text:
            role = "supplier"
        explanation = (
            f"正文直接出现别名 {direct_aliases[0]}，并结合其行业暴露评估。"
            if direct_aliases
            else "公司未被直接点名；结果来自受控行业暴露映射，因此降低关联度与置信度。"
        )
        companies_added.append(
            {
                "entity": entity,
                "role": role,
                "relevance": relevance,
                "direction": direction,
                "strength": "high" if relevance >= 90 else "medium",
                "horizon": horizon,
                "mechanism": mechanism,
                "explanation": explanation,
                "confidence": "high" if direct_aliases else "medium",
            }
        )
    selected_companies = sorted(companies_added, key=lambda item: item["relevance"], reverse=True)[
        :5
    ]
    for payload in selected_companies:
        entity = payload["entity"]
        impact_values = {key: value for key, value in payload.items() if key != "entity"}
        session.add(
            CompanyImpact(
                event_id=event_id,
                entity_id=entity.id,
                evidence_ids=default_evidence_ids,
                analysis_run_id=impact_run.id,
                **impact_values,
            )
        )
    impact_run.output_json = {
        "industry_ids": list(industry_scores)[:3],
        "company_ids": [item["entity"].id for item in selected_companies],
        "evidence_ids": default_evidence_ids,
    }
    session.flush()
    return PreparedAnalysis(
        event_id=event_id,
        input_hash=input_hash,
        combined_text=combined_text_original,
        evidence_ids=tuple(item.id for item in evidence_rows),
        verification_id=verification.id,
        impact_run_id=impact_run.id,
    )


def analyze_event(session: Session, event_id: str, settings: Settings) -> Report:
    input_hash = _analysis_input_hash(session, event_id, settings)
    existing_report = session.scalar(
        select(Report)
        .where(Report.event_id == event_id, Report.input_hash == input_hash)
        .order_by(Report.version.desc())
    )
    if existing_report is not None:
        session.commit()
        return existing_report
    prepared = _prepare_event_analysis(
        session,
        event_id,
        settings,
        input_hash=input_hash,
    )
    report = persist_report(
        session,
        event_id,
        input_hash=prepared.input_hash,
        model=settings.llm_model,
        prompt_version="deterministic-report-v1",
    )
    queue_report_notifications(session, report)
    session.commit()
    return report


def _llm_industry_candidates(session: Session, event_id: str) -> list[Industry]:
    direct_ids = list(
        session.scalars(
            select(IndustryImpact.industry_id)
            .where(IndustryImpact.event_id == event_id)
            .order_by(IndustryImpact.relevance.desc())
            .limit(MAX_LLM_INDUSTRIES)
        )
    )
    candidates = [
        industry for industry_id in direct_ids if (industry := session.get(Industry, industry_id))
    ]
    if len(candidates) < MAX_LLM_INDUSTRIES:
        query = select(Industry)
        if direct_ids:
            query = query.where(Industry.id.not_in(direct_ids))
        candidates.extend(
            session.scalars(query.order_by(Industry.id).limit(MAX_LLM_INDUSTRIES - len(candidates)))
        )
    return candidates


def _llm_company_candidates(session: Session, event_id: str) -> list[Entity]:
    direct_ids = list(
        session.scalars(
            select(CompanyImpact.entity_id)
            .where(CompanyImpact.event_id == event_id)
            .order_by(CompanyImpact.relevance.desc())
        )
    )
    candidates = [entity for entity_id in direct_ids if (entity := session.get(Entity, entity_id))]
    industry_ids = set(
        session.scalars(
            select(IndustryImpact.industry_id).where(IndustryImpact.event_id == event_id)
        )
    )
    if industry_ids and len(candidates) < MAX_LLM_COMPANIES:
        candidates.extend(
            session.scalars(
                select(Entity)
                .where(
                    Entity.entity_type == "company",
                    Entity.industry_id.in_(industry_ids),
                    Entity.id.not_in(direct_ids),
                )
                .order_by(Entity.id)
                .limit(MAX_LLM_COMPANIES - len(candidates))
            )
        )
    return candidates[:MAX_LLM_COMPANIES]


def _llm_prompt_context(session: Session, prepared: PreparedAnalysis) -> LLMPromptContext:
    evidence_rows = list(
        session.scalars(
            select(Evidence)
            .where(Evidence.id.in_(prepared.evidence_ids))
            .order_by(Evidence.id)
            .limit(MAX_LLM_EVIDENCE)
        )
    )
    evidence = [
        {
            "id": item.id,
            "source_tier": item.source_tier,
            "stance": item.stance,
            "quote": item.quote[:MAX_LLM_EVIDENCE_QUOTE_CHARS],
            "independence_group": item.independence_group,
        }
        for item in evidence_rows
    ]
    industry_rows = _llm_industry_candidates(session, prepared.event_id)
    industries = [
        {
            "id": item.id,
            "name": item.name[:MAX_LLM_TARGET_NAME_CHARS],
            "keywords": [
                normalize_text(str(keyword))[:MAX_LLM_KEYWORD_CHARS]
                for keyword in item.keywords[:MAX_LLM_KEYWORDS_PER_INDUSTRY]
            ],
        }
        for item in industry_rows
    ]
    companies = []
    company_rows = _llm_company_candidates(session, prepared.event_id)
    for entity in company_rows:
        aliases = list(
            session.scalars(
                select(EntityAlias.alias)
                .where(EntityAlias.entity_id == entity.id, EntityAlias.negative.is_(False))
                .order_by(EntityAlias.alias)
                .limit(MAX_LLM_ALIASES)
            )
        )
        companies.append(
            {
                "id": entity.id,
                "name": entity.canonical_name[:MAX_LLM_TARGET_NAME_CHARS],
                "industry_id": entity.industry_id,
                "aliases": [alias[:MAX_LLM_ALIAS_CHARS] for alias in aliases],
            }
        )
    payload = compact_json(
        {
            "event_id": prepared.event_id,
            "event_text": prepared.combined_text[:MAX_LLM_EVENT_TEXT_CHARS],
            "evidence": evidence,
            "allowed_industries": industries,
            "allowed_companies": companies,
        }
    )
    if len(payload) > 40_000:
        raise RuntimeError("Bounded LLM prompt unexpectedly exceeds the message contract")
    return LLMPromptContext(
        messages=(
            LLMMessage(
                role="system",
                content=(
                    "You analyze news impacts using only the supplied evidence and target catalogs. "
                    "Return JSON matching the schema. Never invent target IDs or evidence IDs. "
                    "Relevance is 0-100 and is distinct from impact strength and confidence. "
                    "State uncertainty conservatively; this is not investment advice."
                ),
            ),
            LLMMessage(role="user", content=payload),
        ),
        evidence_ids=frozenset(item.id for item in evidence_rows),
        industry_ids=frozenset(item.id for item in industry_rows),
        company_ids=frozenset(item.id for item in company_rows),
    )


def _remaining_llm_budget(session: Session, settings: Settings) -> float:
    start_of_day = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    spent = float(
        session.scalar(
            select(func.coalesce(func.sum(AnalysisRun.cost), 0.0)).where(
                AnalysisRun.created_at >= start_of_day
            )
        )
        or 0.0
    )
    return max(0.0, min(settings.llm_per_event_budget, settings.daily_llm_budget - spent))


def _apply_model_analysis(
    session: Session,
    prepared: PreparedAnalysis,
    validated: ValidatedLLMOutput,
) -> None:
    impact_run = session.get(AnalysisRun, prepared.impact_run_id)
    verification = session.get(Verification, prepared.verification_id)
    if impact_run is None or verification is None:
        raise RuntimeError("Prepared analysis state is missing")
    session.execute(delete(IndustryImpact).where(IndustryImpact.event_id == prepared.event_id))
    session.execute(delete(CompanyImpact).where(CompanyImpact.event_id == prepared.event_id))
    output = validated.output
    for impact in output.industries:
        session.add(
            IndustryImpact(
                event_id=prepared.event_id,
                industry_id=impact.target_id,
                relevance=impact.relevance,
                direction=impact.direction,
                strength=impact.strength,
                horizon=impact.horizon,
                mechanism=impact.mechanism,
                explanation=impact.explanation,
                confidence=impact.confidence,
                evidence_ids=impact.evidence_ids,
                analysis_run_id=impact_run.id,
            )
        )
    for impact in output.companies:
        session.add(
            CompanyImpact(
                event_id=prepared.event_id,
                entity_id=impact.target_id,
                role=impact.role or "subject",
                relevance=impact.relevance,
                direction=impact.direction,
                strength=impact.strength,
                horizon=impact.horizon,
                mechanism=impact.mechanism,
                explanation=impact.explanation,
                confidence=impact.confidence,
                evidence_ids=impact.evidence_ids,
                analysis_run_id=impact_run.id,
            )
        )
    verification.rationale = (
        f"{verification.rationale} Model impact rationale: {output.verification_rationale}"
    )
    impact_run.prompt_version = "structured-impact-v1"
    impact_run.status = "succeeded"
    impact_run.cost = validated.estimated_cost
    impact_run.output_json = {
        "analysis": output.model_dump(mode="json"),
        "attempts": validated.attempts,
        "token_input": validated.token_input,
        "token_output": validated.token_output,
    }
    session.flush()


def _record_llm_failure(
    session: Session,
    *,
    event_id: str,
    input_hash: str,
    settings: Settings,
    idempotency_key: str,
    status: str,
    attempts: int,
    error_code: str,
    message: str,
    token_input: int = 0,
    token_output: int = 0,
    estimated_cost: float = 0.0,
) -> None:
    job = session.scalar(select(PipelineJob).where(PipelineJob.idempotency_key == idempotency_key))
    if job is None:
        job = PipelineJob(job_type="llm-impact", idempotency_key=idempotency_key)
        session.add(job)
    job.status = status
    job.attempts = attempts
    job.last_error = f"{error_code}: {message}"[:1_000]
    job.next_run_at = utcnow() + timedelta(minutes=5) if status == "retry_wait" else None
    session.add(
        AnalysisRun(
            event_id=event_id,
            stage="impact",
            model=settings.llm_model,
            prompt_version="structured-impact-v1",
            schema_version="1",
            input_hash=input_hash,
            output_json={
                "error_code": error_code,
                "attempts": attempts,
                "token_input": token_input,
                "token_output": token_output,
            },
            status=status,
            cost=estimated_cost,
        )
    )
    session.commit()


async def analyze_event_configured(
    session: Session,
    event_id: str,
    settings: Settings,
    *,
    llm_port: LLMPort | None = None,
    force_retry: bool = False,
) -> Report:
    if settings.llm_provider == "deterministic":
        return analyze_event(session, event_id, settings)

    input_hash = _analysis_input_hash(session, event_id, settings)
    existing_report = session.scalar(
        select(Report)
        .where(Report.event_id == event_id, Report.input_hash == input_hash)
        .order_by(Report.version.desc())
    )
    if existing_report is not None:
        session.commit()
        return existing_report

    key_material = f"{event_id}:{input_hash}:{settings.llm_model}:structured-impact-v1"
    idempotency_key = f"llm-impact:{hashlib.sha256(key_material.encode()).hexdigest()}"
    job = session.scalar(select(PipelineJob).where(PipelineJob.idempotency_key == idempotency_key))
    if job is not None and job.status == "dead" and not force_retry:
        session.commit()
        raise LLMContractError(
            "LLM_JOB_DEAD",
            job.last_error or "Previous model analysis exhausted its repair attempt",
            attempts=job.attempts,
        )
    if job is None:
        job = PipelineJob(job_type="llm-impact", idempotency_key=idempotency_key)
        session.add(job)
    job.status = "running"
    job.last_error = None
    job.next_run_at = None
    session.commit()

    prepared = _prepare_event_analysis(
        session,
        event_id,
        settings,
        input_hash=input_hash,
    )
    remaining_budget = _remaining_llm_budget(session, settings)
    if remaining_budget <= 0:
        session.rollback()
        error = LLMContractError(
            "BUDGET_EXCEEDED", "No per-event or daily LLM budget remains", attempts=0
        )
        _record_llm_failure(
            session,
            event_id=event_id,
            input_hash=input_hash,
            settings=settings,
            idempotency_key=idempotency_key,
            status="dead",
            attempts=0,
            error_code=error.code,
            message=str(error),
        )
        raise error

    port = llm_port or OpenAICompatibleLLM(
        base_url=settings.llm_api_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
        input_cost_per_million=settings.llm_input_cost_per_million,
        output_cost_per_million=settings.llm_output_cost_per_million,
    )
    prompt_context = _llm_prompt_context(session, prepared)
    try:
        validated = await complete_model_analysis(
            port,
            messages=list(prompt_context.messages),
            budget=LLMBudget(
                max_output_tokens=settings.llm_max_output_tokens,
                max_cost=remaining_budget,
            ),
            idempotency_key=idempotency_key,
            allowed_evidence_ids=set(prompt_context.evidence_ids),
            allowed_industry_ids=set(prompt_context.industry_ids),
            allowed_company_ids=set(prompt_context.company_ids),
        )
    except LLMContractError as exc:
        session.rollback()
        _record_llm_failure(
            session,
            event_id=event_id,
            input_hash=input_hash,
            settings=settings,
            idempotency_key=idempotency_key,
            status="dead",
            attempts=exc.attempts,
            error_code=exc.code,
            message=str(exc),
            token_input=exc.token_input,
            token_output=exc.token_output,
            estimated_cost=exc.estimated_cost,
        )
        raise
    except (LLMProviderError, httpx.HTTPError) as exc:
        session.rollback()
        _record_llm_failure(
            session,
            event_id=event_id,
            input_hash=input_hash,
            settings=settings,
            idempotency_key=idempotency_key,
            status="retry_wait",
            attempts=max(job.attempts + 1, 1),
            error_code="LLM_PROVIDER_ERROR",
            message=str(exc),
        )
        raise

    _apply_model_analysis(session, prepared, validated)
    report = persist_report(
        session,
        event_id,
        input_hash=prepared.input_hash,
        model=settings.llm_model,
        prompt_version="structured-impact-v1",
    )
    queue_report_notifications(session, report)
    job.status = "succeeded"
    job.attempts = validated.attempts
    job.last_error = None
    session.commit()
    return report


def seed_demo(session: Session, settings: Settings) -> list[str]:
    existing_demo = session.scalar(
        select(func.count()).select_from(EventCluster).where(EventCluster.is_demo.is_(True))
    )
    if existing_demo:
        return []
    event_ids: set[str] = set()
    for payload in load_yaml(settings.config_dir / "demo_articles.yaml").get("articles", []):
        source = session.get(Source, payload["source_id"])
        if source is None:
            raise RuntimeError(f"Demo source is missing: {payload['source_id']}")
        _article, event, _created = ingest_article(session, source, payload)
        event_ids.add(event.id)
    session.commit()
    for event_id in event_ids:
        analyze_event(session, event_id, settings)
    return sorted(event_ids)


async def _fetch_source_entries(
    source: Source,
    settings: Settings,
    limit: int,
) -> tuple[list[Any], int]:
    try:
        return await _fetch_source_url(source, source.entry_url, settings, limit)
    except UnsafeUrlError:
        raise
    except (httpx.HTTPError, ValueError) as primary_error:
        if not source.fallback_url:
            raise
        try:
            return await _fetch_source_url(source, source.fallback_url, settings, limit)
        except UnsafeUrlError:
            raise
        except (httpx.HTTPError, ValueError) as fallback_error:
            raise ValueError(
                f"Primary entry failed: {primary_error}; fallback entry failed: {fallback_error}"
            ) from fallback_error


async def _fetch_source_url(
    source: Source,
    url: str,
    settings: Settings,
    limit: int,
) -> tuple[list[Any], int]:
    parser_name = "metadata" if source.content_policy == "metadata_only" else source.parser
    if source.method in {"rss", "atom"}:
        return await fetch_feed(
            url,
            limit=limit,
            user_agent=settings.outbound_user_agent,
        )
    if source.method == "api":
        return await fetch_api_entries(
            url,
            limit=limit,
            user_agent=settings.outbound_user_agent,
        )
    if source.method == "sitemap":
        return await fetch_sitemap_entries(
            url,
            limit=limit,
            user_agent=settings.outbound_user_agent,
            parser_name=parser_name,
        )
    if source.method == "website":
        return await discover_site_entries(
            url,
            source_id=source.id,
            allowed_source_ids=set(settings.newsplease_discovery_source_ids),
            limit=limit,
            user_agent=settings.outbound_user_agent,
        )
    raise ValueError(f"Method cannot be scheduled for collection: {source.method}")


async def ingest_manual_url(
    session: Session,
    source: Source,
    url: str,
    settings: Settings,
) -> dict[str, Any]:
    if source.is_demo:
        raise ValueError("Manual URLs cannot be attributed to a demo source")
    parser_name = "metadata" if source.content_policy == "metadata_only" else source.parser
    entry, http_status = await fetch_html_entry(
        url,
        user_agent=settings.outbound_user_agent,
        parser_name=parser_name,
    )
    article, event, created = ingest_article(session, source, asdict(entry))
    try:
        report = await analyze_event_configured(session, event.id, settings)
        report_id: str | None = report.id
        analysis_status = "succeeded"
        analysis_error: str | None = None
    except LLMContractError as exc:
        report_id = None
        analysis_status = "dead"
        analysis_error = f"{exc.code}: {exc}"
    except (LLMProviderError, httpx.HTTPError) as exc:
        report_id = None
        analysis_status = "retry_wait"
        analysis_error = str(exc)
    return {
        "source_id": source.id,
        "article_id": article.id,
        "event_id": event.id,
        "report_id": report_id,
        "analysis_status": analysis_status,
        "analysis_error": analysis_error,
        "created": created,
        "http_status": http_status,
    }


async def _enrich_source_entry(
    source: Source,
    entry: Any,
    settings: Settings,
) -> Any:
    if entry.body_excerpt or entry.parse_diagnostics.get("status") == "succeeded":
        return entry
    if source.content_policy == "metadata_only":
        return replace(
            entry,
            parse_diagnostics={"extractor": "metadata", "status": "skipped"},
        )
    try:
        parser_name = "metadata" if source.content_policy == "metadata_only" else source.parser
        extracted, _http_status = await fetch_html_entry(
            entry.url,
            user_agent=settings.outbound_user_agent,
            parser_name=parser_name,
        )
    except (httpx.HTTPError, UnsafeUrlError, ValueError) as exc:
        return replace(
            entry,
            parse_diagnostics={
                "extractor": "newspaper4k" if parser_name == "auto" else parser_name,
                "status": "failed",
                "error": str(exc)[:500],
            },
        )
    return replace(
        entry,
        url=extracted.url,
        summary=extracted.summary or entry.summary,
        published_at=entry.published_at or extracted.published_at,
        updated_at=entry.updated_at or extracted.updated_at,
        author=entry.author or extracted.author,
        body_excerpt=extracted.body_excerpt,
        parse_diagnostics=extracted.parse_diagnostics,
    )


async def _enrich_source_entries(
    source: Source,
    entries: list[Any],
    settings: Settings,
) -> list[Any]:
    semaphore = asyncio.Semaphore(4)

    async def enrich(entry: Any) -> Any:
        async with semaphore:
            return await _enrich_source_entry(source, entry, settings)

    return list(await asyncio.gather(*(enrich(entry) for entry in entries)))


async def pull_sources(
    session: Session,
    settings: Settings,
    source_ids: list[str],
    max_items_per_source: int,
) -> list[dict[str, Any]]:
    query = select(Source).where(
        Source.enabled.is_(True),
        Source.is_demo.is_(False),
        Source.method != "manual",
    )
    if source_ids:
        query = query.where(Source.id.in_(source_ids))
    sources = list(session.scalars(query.order_by(Source.id)))
    results: list[dict[str, Any]] = []
    for source in sources:
        run = SourceRun(source_id=source.id)
        session.add(run)
        session.commit()
        touched_events: set[str] = set()
        try:
            entries, http_status = await _fetch_source_entries(
                source,
                settings,
                max_items_per_source,
            )
            entries = await _enrich_source_entries(source, entries, settings)
            for entry in entries:
                payload = asdict(entry)
                payload["url"] = payload.pop("url")
                _article, event, _created = ingest_article(session, source, payload)
                touched_events.add(event.id)
            run.status = "succeeded"
            run.http_status = http_status
            run.item_count = len(entries)
            source.last_success_at = utcnow()
            source.consecutive_failures = 0
            source.last_error = None
            session.commit()
            analysis_errors = []
            for event_id in touched_events:
                try:
                    await analyze_event_configured(session, event_id, settings)
                except LLMContractError as exc:
                    analysis_errors.append(
                        {"event_id": event_id, "status": "dead", "error": f"{exc.code}: {exc}"}
                    )
                except (LLMProviderError, httpx.HTTPError) as exc:
                    analysis_errors.append(
                        {"event_id": event_id, "status": "retry_wait", "error": str(exc)}
                    )
            results.append(
                {
                    "source_id": source.id,
                    "status": "succeeded",
                    "items": len(entries),
                    "analysis_errors": analysis_errors,
                }
            )
        except UnsafeUrlError as exc:
            session.rollback()
            run = session.get(SourceRun, run.id)
            source = session.get(Source, source.id)
            assert run is not None and source is not None
            run.status = "dead"
            run.error_code = "SOURCE_FORBIDDEN"
            run.error_message = str(exc)
            source.consecutive_failures += 1
            source.last_error = str(exc)
            session.commit()
            results.append({"source_id": source.id, "status": "dead", "error": str(exc)})
        except (httpx.HTTPError, ValueError) as exc:
            session.rollback()
            run = session.get(SourceRun, run.id)
            source = session.get(Source, source.id)
            assert run is not None and source is not None
            run.status = "retry_wait"
            run.error_code = (
                "SOURCE_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "SOURCE_ERROR"
            )
            run.error_message = str(exc)[:1000]
            source.consecutive_failures += 1
            source.last_error = str(exc)[:1000]
            session.commit()
            results.append({"source_id": source.id, "status": "retry_wait", "error": str(exc)})
        finally:
            current_run = session.get(SourceRun, run.id)
            if current_run:
                current_run.ended_at = utcnow()
                session.commit()
    return results


async def test_source(
    session: Session,
    source: Source,
    settings: Settings,
) -> dict[str, Any]:
    run = SourceRun(source_id=source.id)
    session.add(run)
    session.commit()
    try:
        if source.method == "fixture":
            result = {
                "status": "ok",
                "method": "fixture",
                "items": 0,
                "note": "local demo source",
            }
            run.http_status = 200
        elif source.method in {"rss", "atom", "api", "sitemap", "website"}:
            entries, http_status = await _fetch_source_entries(source, settings, 3)
            result = {
                "status": "ok",
                "method": source.method,
                "http_status": http_status,
                "items": len(entries),
                "sample_titles": [entry.title for entry in entries],
            }
            run.http_status = http_status
            run.item_count = len(entries)
        elif source.method == "manual":
            parser_name = "metadata" if source.content_policy == "metadata_only" else source.parser
            entry, http_status = await fetch_html_entry(
                source.entry_url,
                user_agent=settings.outbound_user_agent,
                parser_name=parser_name,
            )
            result = {
                "status": "ok",
                "method": source.method,
                "http_status": http_status,
                "items": 1,
                "sample_titles": [entry.title],
            }
            run.http_status = http_status
            run.item_count = 1
        else:
            raise ValueError(f"Method not implemented: {source.method}")
        run.status = "succeeded"
        source.last_success_at = utcnow()
        source.consecutive_failures = 0
        source.last_error = None
        return result
    except UnsafeUrlError as exc:
        run.status = "dead"
        run.error_code = "SOURCE_FORBIDDEN"
        run.error_message = str(exc)[:1000]
        source.consecutive_failures += 1
        source.last_error = str(exc)[:1000]
        raise
    except (httpx.HTTPError, ValueError) as exc:
        run.status = "retry_wait"
        run.error_code = (
            "SOURCE_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "SOURCE_ERROR"
        )
        run.error_message = str(exc)[:1000]
        source.consecutive_failures += 1
        source.last_error = str(exc)[:1000]
        raise
    finally:
        run.ended_at = utcnow()
        session.commit()


def list_events(
    session: Session,
    *,
    query: str | None = None,
    verification_status: str | None = None,
    region: str | None = None,
    language: str | None = None,
    source_id: str | None = None,
    industry_id: str | None = None,
    company_id: str | None = None,
    direction: str | None = None,
    strength: str | None = None,
    demo: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    events = select(EventCluster).where(EventCluster.state == "active")
    if query:
        events = events.where(EventCluster.title.ilike(f"%{query}%"))
    if demo is not None:
        events = events.where(EventCluster.is_demo.is_(demo))
    source_filters = []
    if region:
        source_filters.append(Source.region == region)
    if language:
        source_filters.append(Article.language == language)
    if source_id:
        source_filters.append(Article.source_id == source_id)
    if source_filters:
        source_event_ids = (
            select(EventArticle.event_id)
            .join(Article, Article.id == EventArticle.article_id)
            .join(Source, Source.id == Article.source_id)
            .where(*source_filters)
        )
        events = events.where(EventCluster.id.in_(source_event_ids))
    if verification_status:
        latest_verification_status = (
            select(Verification.status)
            .join(Claim, Claim.id == Verification.claim_id)
            .where(
                Claim.event_id == EventCluster.id,
                Claim.is_current.is_(True),
            )
            .order_by(Verification.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        events = events.where(latest_verification_status == verification_status)

    impact_filters = []
    if direction:
        impact_filters.append(("direction", direction))
    if strength:
        impact_filters.append(("strength", strength))
    if industry_id:
        conditions = [IndustryImpact.industry_id == industry_id]
        conditions.extend(
            getattr(IndustryImpact, field) == value for field, value in impact_filters
        )
        events = events.where(
            EventCluster.id.in_(select(IndustryImpact.event_id).where(*conditions))
        )
    if company_id:
        conditions = [CompanyImpact.entity_id == company_id]
        conditions.extend(getattr(CompanyImpact, field) == value for field, value in impact_filters)
        events = events.where(
            EventCluster.id.in_(select(CompanyImpact.event_id).where(*conditions))
        )
    if impact_filters and not industry_id and not company_id:
        industry_conditions = [
            getattr(IndustryImpact, field) == value for field, value in impact_filters
        ]
        company_conditions = [
            getattr(CompanyImpact, field) == value for field, value in impact_filters
        ]
        impact_event_ids = (
            select(IndustryImpact.event_id)
            .where(*industry_conditions)
            .union(select(CompanyImpact.event_id).where(*company_conditions))
        )
        events = events.where(EventCluster.id.in_(impact_event_ids))
    events = events.order_by(EventCluster.last_seen.desc()).limit(limit)

    rows: list[dict[str, Any]] = []
    for event in session.scalars(events):
        article_count = int(
            session.scalar(
                select(func.count())
                .select_from(EventArticle)
                .where(EventArticle.event_id == event.id)
            )
            or 0
        )
        article_ids = list(
            session.scalars(
                select(EventArticle.article_id).where(EventArticle.event_id == event.id)
            )
        )
        chain_count = int(
            session.scalar(
                select(func.count(func.distinct(Article.independence_group))).where(
                    Article.id.in_(article_ids)
                )
            )
            or 0
        )
        claim = session.scalar(
            select(Claim).where(Claim.event_id == event.id, Claim.is_current.is_(True))
        )
        verification = (
            session.scalar(
                select(Verification)
                .where(Verification.claim_id == claim.id)
                .order_by(Verification.created_at.desc())
            )
            if claim
            else None
        )
        regions = sorted(
            session.scalars(
                select(Source.region)
                .join(Article, Article.source_id == Source.id)
                .where(Article.id.in_(article_ids))
                .distinct()
            )
        )
        languages = sorted(
            session.scalars(select(Article.language).where(Article.id.in_(article_ids)).distinct())
        )
        source_ids = sorted(
            session.scalars(select(Article.source_id).where(Article.id.in_(article_ids)).distinct())
        )
        latest_report = session.scalar(
            select(Report).where(Report.event_id == event.id).order_by(Report.version.desc())
        )
        max_relevance = max(
            [
                int(
                    session.scalar(
                        select(func.max(IndustryImpact.relevance)).where(
                            IndustryImpact.event_id == event.id
                        )
                    )
                    or 0
                ),
                int(
                    session.scalar(
                        select(func.max(CompanyImpact.relevance)).where(
                            CompanyImpact.event_id == event.id
                        )
                    )
                    or 0
                ),
            ]
        )
        rows.append(
            {
                "id": event.id,
                "title": event.title,
                "last_seen": event.last_seen,
                "is_demo": event.is_demo,
                "article_count": article_count,
                "independent_chain_count": chain_count,
                "verification_status": verification.status if verification else "pending",
                "verification_confidence": verification.confidence if verification else "low",
                "regions": regions,
                "languages": languages,
                "source_ids": source_ids,
                "max_relevance": max_relevance,
                "report_id": latest_report.id if latest_report else None,
            }
        )
    return rows


def event_detail(session: Session, event_id: str) -> dict[str, Any]:
    event = session.get(EventCluster, event_id)
    if event is None:
        raise LookupError(f"Event not found: {event_id}")
    rows = session.execute(
        select(Article, Source)
        .join(EventArticle, EventArticle.article_id == Article.id)
        .join(Source, Source.id == Article.source_id)
        .where(EventArticle.event_id == event_id)
        .order_by(Article.published_at)
    ).all()
    claims = list(
        session.scalars(select(Claim).where(Claim.event_id == event_id, Claim.is_current.is_(True)))
    )
    claim_ids = [claim.id for claim in claims]
    evidence = list(session.scalars(select(Evidence).where(Evidence.claim_id.in_(claim_ids))))
    verification = (
        session.scalar(
            select(Verification)
            .where(Verification.claim_id.in_(claim_ids))
            .order_by(Verification.created_at.desc())
        )
        if claim_ids
        else None
    )
    industries = [
        {
            "id": impact.id,
            "target_id": industry.id,
            "name": industry.name,
            "relevance": impact.relevance,
            "direction": impact.direction,
            "strength": impact.strength,
            "horizon": impact.horizon,
            "mechanism": impact.mechanism,
            "explanation": impact.explanation,
            "confidence": impact.confidence,
            "evidence_ids": impact.evidence_ids,
        }
        for impact, industry in session.execute(
            select(IndustryImpact, Industry)
            .join(Industry, Industry.id == IndustryImpact.industry_id)
            .where(IndustryImpact.event_id == event_id)
            .order_by(IndustryImpact.relevance.desc())
        )
    ]
    companies = [
        {
            "id": impact.id,
            "target_id": entity.id,
            "name": entity.canonical_name,
            "identifiers": entity.identifiers_json,
            "role": impact.role,
            "relevance": impact.relevance,
            "direction": impact.direction,
            "strength": impact.strength,
            "horizon": impact.horizon,
            "mechanism": impact.mechanism,
            "explanation": impact.explanation,
            "confidence": impact.confidence,
            "evidence_ids": impact.evidence_ids,
        }
        for impact, entity in session.execute(
            select(CompanyImpact, Entity)
            .join(Entity, Entity.id == CompanyImpact.entity_id)
            .where(CompanyImpact.event_id == event_id)
            .order_by(CompanyImpact.relevance.desc())
        )
    ]
    latest_report = session.scalar(
        select(Report).where(Report.event_id == event_id).order_by(Report.version.desc())
    )
    article_payload = []
    for article, source in rows:
        version = _latest_version(session, article.id)
        article_payload.append(
            {
                "id": article.id,
                "title": article.title,
                "url": article.original_url,
                "published_at": article.published_at,
                "source_name": source.name,
                "source_tier": source.tier,
                "official": source.official,
                "summary": version.summary if version else "",
                "independence_group": article.independence_group,
                "version_count": len(article.versions),
            }
        )
    return {
        "event": event,
        "articles": article_payload,
        "claims": claims,
        "evidence": evidence,
        "verification": verification,
        "industries": industries,
        "companies": companies,
        "report": latest_report,
        "independent_chain_count": len({item["independence_group"] for item in article_payload}),
    }


def submit_feedback(session: Session, payload: FeedbackCreate) -> Feedback:
    feedback = Feedback(**payload.model_dump(), analysis_version="rules-v1")
    session.add(feedback)
    session.commit()
    return feedback


async def reanalyze_event(session: Session, event_id: str, settings: Settings) -> Report:
    return await analyze_event_configured(session, event_id, settings, force_retry=True)


async def _analyze_mutated_events(
    session: Session,
    event_ids: list[str],
    settings: Settings,
) -> tuple[str, str | None]:
    analysis_status = "succeeded"
    errors: list[str] = []
    for event_id in event_ids:
        try:
            await analyze_event_configured(session, event_id, settings)
        except LLMContractError as exc:
            analysis_status = "dead"
            errors.append(f"{event_id}: {exc.code}")
        except (LLMProviderError, httpx.HTTPError):
            if analysis_status == "succeeded":
                analysis_status = "retry_wait"
            errors.append(f"{event_id}: LLM_PROVIDER_ERROR")
    return analysis_status, "; ".join(errors) or None


def set_event_lock(
    session: Session,
    event_id: str,
    *,
    locked: bool,
    reason: str,
    actor: str,
) -> EventCluster:
    event = session.get(EventCluster, event_id)
    if event is None:
        raise LookupError(f"Event not found: {event_id}")
    if event.state != "active":
        raise ValueError("Only active events can be locked or unlocked")
    if event.locked == locked:
        return event
    event.locked = locked
    session.add(
        Feedback(
            target_type="cluster",
            target_id=event_id,
            verdict="correct",
            reason=f"{'Locked' if locked else 'Unlocked'} event: {reason}",
            actor=actor,
            analysis_version="manual-lock-v1",
        )
    )
    session.commit()
    return event


async def merge_events(
    session: Session, event_ids: list[str], reason: str, settings: Settings
) -> EventMutationResult:
    target_id = event_ids[0]
    target = session.get(EventCluster, target_id)
    if target is None:
        raise LookupError(f"Event not found: {target_id}")
    for source_id in event_ids[1:]:
        source_event = session.get(EventCluster, source_id)
        if source_event is None:
            raise LookupError(f"Event not found: {source_id}")
        memberships = list(
            session.scalars(select(EventArticle).where(EventArticle.event_id == source_id))
        )
        for membership in memberships:
            already = session.get(
                EventArticle, {"event_id": target_id, "article_id": membership.article_id}
            )
            if already is None:
                membership.event_id = target_id
            else:
                session.delete(membership)
        source_event.state = "merged"
        target.last_seen = max(_ensure_utc(target.last_seen), _ensure_utc(source_event.last_seen))
    session.add(
        Feedback(
            target_type="cluster",
            target_id=target_id,
            verdict="correct",
            reason=f"Merged {event_ids}: {reason}",
            actor="local-analyst",
            analysis_version="manual-merge-v1",
        )
    )
    session.commit()
    analysis_status, analysis_error = await _analyze_mutated_events(session, [target_id], settings)
    return EventMutationResult(
        event_id=target_id,
        analysis_status=analysis_status,
        analysis_error=analysis_error,
    )


async def split_event(
    session: Session,
    event_id: str,
    article_ids: list[str],
    reason: str,
    settings: Settings,
) -> EventMutationResult:
    source_event = session.get(EventCluster, event_id)
    if source_event is None:
        raise LookupError(f"Event not found: {event_id}")
    selected = list(
        session.scalars(
            select(EventArticle).where(
                EventArticle.event_id == event_id, EventArticle.article_id.in_(article_ids)
            )
        )
    )
    if len(selected) != len(set(article_ids)):
        raise ValueError("Every split article must belong to the source event")
    if len(selected) >= len(
        list(session.scalars(select(EventArticle).where(EventArticle.event_id == event_id)))
    ):
        raise ValueError("A split must leave at least one article in the source event")
    representative = session.get(Article, selected[0].article_id)
    assert representative is not None
    new_event = EventCluster(
        representative_article_id=representative.id,
        title=representative.title,
        first_seen=representative.published_at or utcnow(),
        last_seen=representative.last_seen_at,
        is_demo=source_event.is_demo,
    )
    session.add(new_event)
    session.flush()
    for membership in selected:
        membership.event_id = new_event.id
    session.add(
        Feedback(
            target_type="cluster",
            target_id=event_id,
            verdict="incorrect",
            reason=f"Split to {new_event.id}: {reason}",
            actor="local-analyst",
            analysis_version="manual-split-v1",
        )
    )
    session.commit()
    analysis_status, analysis_error = await _analyze_mutated_events(
        session,
        [event_id, new_event.id],
        settings,
    )
    return EventMutationResult(
        event_id=new_event.id,
        analysis_status=analysis_status,
        analysis_error=analysis_error,
    )


def system_summary(session: Session, settings: Settings) -> dict[str, Any]:
    return {
        "sources": int(session.scalar(select(func.count()).select_from(Source)) or 0),
        "healthy_sources": int(
            session.scalar(
                select(func.count())
                .select_from(Source)
                .where(
                    Source.last_success_at.is_not(None),
                    Source.consecutive_failures == 0,
                )
            )
            or 0
        ),
        "articles": int(session.scalar(select(func.count()).select_from(Article)) or 0),
        "events": int(session.scalar(select(func.count()).select_from(EventCluster)) or 0),
        "reports": int(session.scalar(select(func.count()).select_from(Report)) or 0),
        "dead_jobs": int(
            session.scalar(
                select(func.count()).select_from(PipelineJob).where(PipelineJob.status == "dead")
            )
            or 0
        ),
        "database": settings.database_url.rsplit("/", 1)[-1],
        "analysis_mode": f"{settings.llm_provider}:{settings.llm_model}",
        "search_provider": settings.search_provider,
        "trendradar_enabled": settings.trendradar_enabled,
    }
