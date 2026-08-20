from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from .adapters.http_sources import fetch_api_entries, fetch_html_entry, fetch_sitemap_entries
from .adapters.rss import fetch_feed
from .catalog import load_yaml
from .config import Settings
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
    for key, value in changes.items():
        setattr(source, key, value)
    session.commit()
    return source


def _find_cluster(
    session: Session, title: str, published_at: datetime | None
) -> tuple[EventCluster | None, float]:
    cutoff = (published_at or utcnow()) - timedelta(days=7)
    candidates = session.scalars(
        select(EventCluster)
        .where(EventCluster.last_seen >= cutoff, EventCluster.locked.is_(False))
        .order_by(EventCluster.last_seen.desc())
        .limit(200)
    )
    best: EventCluster | None = None
    best_score = 0.0
    for event in candidates:
        score = jaccard_similarity(title, event.title)
        if score > best_score:
            best, best_score = event, score
    return (best, best_score) if best_score >= 0.20 else (None, best_score)


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
        event, score = _find_cluster(session, title, published_at)
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


def analyze_event(session: Session, event_id: str, settings: Settings) -> Report:
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
    input_hash = _event_input_hash(session, event_id)

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
    report = persist_report(
        session,
        event_id,
        input_hash=input_hash,
        model=settings.llm_model,
        prompt_version="deterministic-report-v1",
    )
    queue_report_notifications(session, report)
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
    if source.method in {"rss", "atom"}:
        return await fetch_feed(
            source.entry_url,
            limit=limit,
            user_agent=settings.outbound_user_agent,
        )
    if source.method == "api":
        return await fetch_api_entries(
            source.entry_url,
            limit=limit,
            user_agent=settings.outbound_user_agent,
        )
    if source.method == "sitemap":
        return await fetch_sitemap_entries(
            source.entry_url,
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
    entry, http_status = await fetch_html_entry(
        url,
        user_agent=settings.outbound_user_agent,
    )
    article, event, created = ingest_article(session, source, asdict(entry))
    report = analyze_event(session, event.id, settings)
    return {
        "source_id": source.id,
        "article_id": article.id,
        "event_id": event.id,
        "report_id": report.id,
        "created": created,
        "http_status": http_status,
    }


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
            for event_id in touched_events:
                analyze_event(session, event_id, settings)
            results.append({"source_id": source.id, "status": "succeeded", "items": len(entries)})
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
        elif source.method in {"rss", "atom", "api", "sitemap"}:
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
            entry, http_status = await fetch_html_entry(
                source.entry_url,
                user_agent=settings.outbound_user_agent,
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
    demo: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    events = select(EventCluster).order_by(EventCluster.last_seen.desc()).limit(limit)
    if query:
        events = events.where(EventCluster.title.ilike(f"%{query}%"))
    if demo is not None:
        events = events.where(EventCluster.is_demo.is_(demo))
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
        if verification_status and (
            verification is None or verification.status != verification_status
        ):
            continue
        regions = list(
            session.scalars(
                select(Source.region)
                .join(Article, Article.source_id == Source.id)
                .where(Article.id.in_(article_ids))
                .distinct()
            )
        )
        if region and region not in regions:
            continue
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


def reanalyze_event(session: Session, event_id: str, settings: Settings) -> Report:
    return analyze_event(session, event_id, settings)


def merge_events(session: Session, event_ids: list[str], reason: str, settings: Settings) -> str:
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
    analyze_event(session, target_id, settings)
    return target_id


def split_event(
    session: Session,
    event_id: str,
    article_ids: list[str],
    reason: str,
    settings: Settings,
) -> str:
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
    analyze_event(session, event_id, settings)
    analyze_event(session, new_event.id, settings)
    return new_event.id


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
