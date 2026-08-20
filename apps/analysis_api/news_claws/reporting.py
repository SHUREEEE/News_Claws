from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Article,
    ArticleVersion,
    Claim,
    CompanyImpact,
    Entity,
    EventArticle,
    EventCluster,
    Evidence,
    Industry,
    IndustryImpact,
    Report,
    Source,
    Verification,
)
from .schemas import (
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

DISCLAIMER = "本分析仅用于信息辅助，不构成投资、法律或其他专业建议。演示数据不代表真实事件。"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _latest_versions(session: Session, article_ids: list[str]) -> dict[str, ArticleVersion]:
    result: dict[str, ArticleVersion] = {}
    rows = session.scalars(
        select(ArticleVersion)
        .where(ArticleVersion.article_id.in_(article_ids))
        .order_by(ArticleVersion.fetched_at.desc())
    )
    for row in rows:
        result.setdefault(row.article_id, row)
    return result


def _direction(value: str) -> Direction:
    return Direction(value if value in Direction._value2member_map_ else "unknown")


def _confidence(value: str) -> Confidence:
    return Confidence(value if value in Confidence._value2member_map_ else "low")


def _strength(value: str) -> Strength:
    return Strength(value if value in Strength._value2member_map_ else "low")


def build_report_contract(
    session: Session,
    event_id: str,
    *,
    report_version: int,
    model: str,
    prompt_version: str,
) -> ReportContract:
    event = session.get(EventCluster, event_id)
    if event is None:
        raise LookupError(f"Event not found: {event_id}")

    article_rows = session.execute(
        select(Article, Source)
        .join(EventArticle, EventArticle.article_id == Article.id)
        .join(Source, Source.id == Article.source_id)
        .where(EventArticle.event_id == event_id)
        .order_by(Article.published_at.desc())
    ).all()
    articles = [row[0] for row in article_rows]
    versions = _latest_versions(session, [article.id for article in articles])
    current_claims = list(
        session.scalars(select(Claim).where(Claim.event_id == event_id, Claim.is_current.is_(True)))
    )
    if not current_claims:
        raise ValueError("Cannot build a report without a current claim")
    claim_ids = [claim.id for claim in current_claims]
    evidence = list(session.scalars(select(Evidence).where(Evidence.claim_id.in_(claim_ids))))
    evidence_ids = {item.id for item in evidence}
    latest_verification = session.scalar(
        select(Verification)
        .where(Verification.claim_id.in_(claim_ids))
        .order_by(Verification.created_at.desc())
    )
    if latest_verification is None:
        raise ValueError("Cannot build a report without verification")

    supporting = [item.id for item in evidence if item.stance == "supports"]
    conflicting = [
        item.id for item in evidence if item.stance in {"conflicts", "withdrawn", "disproves"}
    ]
    verification = VerificationContract(
        status=VerificationStatus(latest_verification.status),
        confidence=_confidence(latest_verification.confidence),
        claim_ids=claim_ids,
        supporting_evidence_ids=supporting,
        conflicting_evidence_ids=conflicting,
        rationale=latest_verification.rationale,
    )

    industries: list[ImpactContract] = []
    for impact, industry in session.execute(
        select(IndustryImpact, Industry)
        .join(Industry, Industry.id == IndustryImpact.industry_id)
        .where(IndustryImpact.event_id == event_id)
        .order_by(IndustryImpact.relevance.desc())
        .limit(3)
    ):
        industries.append(
            ImpactContract(
                target_id=industry.id,
                target_name=industry.name,
                relevance=impact.relevance,
                direction=_direction(impact.direction),
                strength=_strength(impact.strength),
                horizon=impact.horizon,
                mechanism=impact.mechanism,
                explanation=impact.explanation,
                confidence=_confidence(impact.confidence),
                evidence_ids=impact.evidence_ids,
            )
        )

    companies: list[ImpactContract] = []
    for impact, entity in session.execute(
        select(CompanyImpact, Entity)
        .join(Entity, Entity.id == CompanyImpact.entity_id)
        .where(CompanyImpact.event_id == event_id)
        .order_by(CompanyImpact.relevance.desc())
        .limit(5)
    ):
        companies.append(
            ImpactContract(
                target_id=entity.id,
                target_name=entity.canonical_name,
                role=impact.role,
                relevance=impact.relevance,
                direction=_direction(impact.direction),
                strength=_strength(impact.strength),
                horizon=impact.horizon,
                mechanism=impact.mechanism,
                explanation=impact.explanation,
                confidence=_confidence(impact.confidence),
                evidence_ids=impact.evidence_ids,
            )
        )

    summary = []
    for article in articles:
        version = versions.get(article.id)
        item = (version.summary if version else "") or article.title
        if item not in summary:
            summary.append(item[:360])
        if len(summary) == 3:
            break
    directions = {impact.direction for impact in industries + companies}
    if len(directions) > 1:
        tone = "mixed"
    elif directions == {Direction.POSITIVE}:
        tone = "positive"
    elif directions == {Direction.NEGATIVE}:
        tone = "negative"
    else:
        tone = "neutral"

    generated_at = datetime.now(UTC)
    data_cutoff = max((_as_utc(article.last_seen_at) for article in articles), default=generated_at)
    report = ReportContract(
        event_id=event.id,
        report_version=report_version,
        headline=event.title,
        summary=summary or [event.title],
        overall_tone=tone,
        verification=verification,
        industries=industries,
        companies=companies,
        source_links=[
            SourceLink(
                article_id=article.id,
                source_name=source.name,
                url=article.original_url,
                title=article.title,
                published_at=article.published_at,
                independence_group=article.independence_group,
            )
            for article, source in article_rows
        ],
        generated_at=generated_at,
        data_cutoff_at=data_cutoff,
        model=model,
        prompt_version=prompt_version,
        disclaimer=DISCLAIMER,
    )
    validate_evidence_whitelist(report, evidence_ids)
    return report


def render_markdown(report: ReportContract) -> str:
    lines = [
        f"# {report.headline}",
        "",
        f"- 核实状态: `{report.verification.status.value}`",
        f"- 置信度: `{report.verification.confidence.value}`",
        f"- 数据截止: `{report.data_cutoff_at.isoformat()}`",
        "",
        "## 摘要",
        "",
    ]
    lines.extend(f"- {item}" for item in report.summary)
    lines.extend(["", "## 行业影响", ""])
    lines.extend(
        f"- {item.target_name}: 关联度 {item.relevance}, {item.direction.value}/{item.strength.value}; {item.explanation}"
        for item in report.industries
    )
    lines.extend(["", "## 公司影响", ""])
    lines.extend(
        f"- {item.target_name}: {item.role}, 关联度 {item.relevance}, {item.direction.value}/{item.strength.value}; {item.explanation}"
        for item in report.companies
    )
    lines.extend(["", "## 来源", ""])
    lines.extend(
        f"- [{item.source_name}: {item.title}]({item.url})" for item in report.source_links
    )
    lines.extend(["", report.disclaimer, ""])
    return "\n".join(lines)


def render_html(report: ReportContract) -> str:
    summaries = "".join(f"<li>{escape(item)}</li>" for item in report.summary)
    industries = "".join(
        f"<tr><td>{escape(item.target_name)}</td><td>{item.relevance}</td>"
        f"<td>{escape(item.direction.value)}</td><td>{escape(item.strength.value)}</td>"
        f"<td>{escape(item.explanation)}</td></tr>"
        for item in report.industries
    )
    companies = "".join(
        f"<tr><td>{escape(item.target_name)}</td><td>{escape(item.role or '')}</td>"
        f"<td>{item.relevance}</td><td>{escape(item.direction.value)}</td>"
        f"<td>{escape(item.explanation)}</td></tr>"
        for item in report.companies
    )
    sources = "".join(
        f'<li><a href="{escape(item.url, quote=True)}" rel="noopener noreferrer">'
        f"{escape(item.source_name)}: {escape(item.title)}</a></li>"
        for item in report.source_links
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(report.headline)}</title><link rel="stylesheet" href="/static/report.css"></head>
<body><main><h1>{escape(report.headline)}</h1><p class="meta">{escape(report.verification.status.value)} / {escape(report.verification.confidence.value)} / {escape(report.generated_at.isoformat())}</p>
<h2>摘要</h2><ul>{summaries}</ul><h2>核实结论</h2><p>{escape(report.verification.rationale)}</p>
<h2>行业影响</h2><table><thead><tr><th>行业</th><th>关联度</th><th>方向</th><th>强度</th><th>机制</th></tr></thead><tbody>{industries}</tbody></table>
<h2>公司影响</h2><table><thead><tr><th>公司</th><th>角色</th><th>关联度</th><th>方向</th><th>机制</th></tr></thead><tbody>{companies}</tbody></table>
<h2>来源</h2><ul>{sources}</ul><p class="meta">{escape(report.disclaimer)}</p></main></body></html>"""


def persist_report(
    session: Session,
    event_id: str,
    *,
    input_hash: str,
    model: str,
    prompt_version: str,
) -> Report:
    latest = session.scalar(
        select(Report).where(Report.event_id == event_id).order_by(Report.version.desc())
    )
    if latest is not None and latest.input_hash == input_hash:
        return latest
    next_version = (latest.version if latest else 0) + 1
    contract = build_report_contract(
        session,
        event_id,
        report_version=next_version,
        model=model,
        prompt_version=prompt_version,
    )
    content_json = contract.model_dump(mode="json")
    stable_hash = hashlib.sha256(
        json.dumps(content_json, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    report = Report(
        event_id=event_id,
        version=next_version,
        content_json=content_json,
        content_markdown=render_markdown(contract),
        content_html=render_html(contract),
        generated_at=contract.generated_at,
        data_cutoff_at=contract.data_cutoff_at,
        input_hash=input_hash or stable_hash,
    )
    session.add(report)
    session.flush()
    return report


def report_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(Report)) or 0)
