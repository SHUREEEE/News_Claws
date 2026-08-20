from __future__ import annotations

import hashlib
import smtplib
import ssl
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    CompanyImpact,
    Entity,
    Industry,
    IndustryImpact,
    Notification,
    Report,
    Subscription,
    utcnow,
)
from .schemas import SubscriptionCreate, SubscriptionUpdate

EmailSender = Callable[[Settings, str, str, str], None]
NOTIFICATION_SEMANTIC_VERSION = "email-v1"
MAX_NOTIFICATION_ATTEMPTS = 5


def _target_hash(email: str) -> str:
    return hashlib.sha256(email.strip().casefold().encode("utf-8")).hexdigest()


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _validate_targets(
    session: Session,
    company_ids: list[str],
    industry_ids: list[str],
) -> None:
    known_companies = set(
        session.scalars(
            select(Entity.id).where(
                Entity.entity_type == "company",
                Entity.id.in_(company_ids),
            )
        )
    )
    known_industries = set(
        session.scalars(select(Industry.id).where(Industry.id.in_(industry_ids)))
    )
    missing_companies = set(company_ids) - known_companies
    missing_industries = set(industry_ids) - known_industries
    if missing_companies or missing_industries:
        raise ValueError(
            "Unknown subscription targets: "
            f"companies={sorted(missing_companies)}, "
            f"industries={sorted(missing_industries)}"
        )


def create_subscription(session: Session, payload: SubscriptionCreate) -> Subscription:
    email = payload.email.casefold()
    if session.scalar(select(Subscription).where(Subscription.email == email)):
        raise ValueError("A subscription already exists for this email address")
    company_ids = _deduplicate(payload.company_ids)
    industry_ids = _deduplicate(payload.industry_ids)
    _validate_targets(session, company_ids, industry_ids)
    subscription = Subscription(
        **payload.model_dump(
            exclude={"email", "company_ids", "industry_ids"},
        ),
        email=email,
        company_ids=company_ids,
        industry_ids=industry_ids,
    )
    session.add(subscription)
    session.commit()
    return subscription


def update_subscription(
    session: Session,
    subscription: Subscription,
    payload: SubscriptionUpdate,
) -> Subscription:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise ValueError("At least one subscription field must be provided")
    if changes.get("email"):
        changes["email"] = changes["email"].casefold()
        duplicate = session.scalar(
            select(Subscription).where(
                Subscription.email == changes["email"],
                Subscription.id != subscription.id,
            )
        )
        if duplicate:
            raise ValueError("A subscription already exists for this email address")
    company_ids = _deduplicate(changes.get("company_ids", subscription.company_ids))
    industry_ids = _deduplicate(changes.get("industry_ids", subscription.industry_ids))
    _validate_targets(session, company_ids, industry_ids)
    changes["company_ids"] = company_ids
    changes["industry_ids"] = industry_ids
    for key, value in changes.items():
        setattr(subscription, key, value)
    session.commit()
    return subscription


def queue_report_notifications(session: Session, report: Report) -> int:
    company_relevance = {
        entity_id: relevance
        for entity_id, relevance in session.execute(
            select(CompanyImpact.entity_id, CompanyImpact.relevance).where(
                CompanyImpact.event_id == report.event_id
            )
        ).all()
    }
    industry_relevance = {
        industry_id: relevance
        for industry_id, relevance in session.execute(
            select(IndustryImpact.industry_id, IndustryImpact.relevance).where(
                IndustryImpact.event_id == report.event_id
            )
        ).all()
    }
    queued = 0
    for subscription in session.scalars(select(Subscription).where(Subscription.enabled.is_(True))):
        scores: list[int] = []
        if subscription.company_ids:
            scores.extend(
                company_relevance[target]
                for target in subscription.company_ids
                if target in company_relevance
            )
        if subscription.industry_ids:
            scores.extend(
                industry_relevance[target]
                for target in subscription.industry_ids
                if target in industry_relevance
            )
        if not subscription.company_ids and not subscription.industry_ids:
            scores.extend(company_relevance.values())
            scores.extend(industry_relevance.values())
        if not scores or max(scores) < subscription.min_relevance:
            continue

        target_hash = _target_hash(subscription.email)
        idempotency_key = f"{NOTIFICATION_SEMANTIC_VERSION}:{report.id}:{target_hash}"
        if session.scalar(
            select(Notification).where(Notification.idempotency_key == idempotency_key)
        ):
            continue
        session.add(
            Notification(
                report_id=report.id,
                channel="email",
                target_hash=target_hash,
                idempotency_key=idempotency_key,
            )
        )
        queued += 1
    return queued


def send_smtp_email(
    settings: Settings,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as client:
        client.ehlo()
        if settings.smtp_starttls:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


def _daily_is_due(subscription: Subscription, now: datetime) -> bool:
    last_sent_at = subscription.last_sent_at
    if last_sent_at is not None:
        if last_sent_at.tzinfo is None:
            last_sent_at = last_sent_at.replace(tzinfo=UTC)
        if last_sent_at.astimezone(UTC).date() == now.date():
            return False
    return now.hour >= subscription.digest_hour_utc


def _daily_digest(reports: list[Report], now: datetime) -> tuple[str, str]:
    subject = f"[News Claws] Daily digest {now.date().isoformat()}"
    sections = [
        f"# News Claws daily digest - {now.date().isoformat()}",
        "",
        f"{len(reports)} matched event(s).",
    ]
    for report in reports:
        headline = str(report.content_json.get("headline") or report.event_id)
        summary = report.content_json.get("summary") or []
        sections.extend(["", f"## {headline}"])
        sections.extend(f"- {item}" for item in summary[:3])
    sections.extend(["", "This report is informational and is not investment advice."])
    return subject, "\n".join(sections)


def _mark_failure(notifications: list[Notification], error: Exception) -> None:
    message = str(error)[:1000]
    for notification in notifications:
        notification.attempts += 1
        notification.last_error = message
        notification.status = (
            "dead" if notification.attempts >= MAX_NOTIFICATION_ATTEMPTS else "retry_wait"
        )


def _mark_sent(notifications: list[Notification]) -> None:
    for notification in notifications:
        notification.attempts += 1
        notification.status = "sent"
        notification.last_error = None


def dispatch_pending_notifications(
    session: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
    sender: EmailSender = send_smtp_email,
) -> dict[str, Any]:
    if not settings.notification_enabled:
        return {"status": "disabled", "sent": 0, "failed": 0, "deferred": 0}

    current_time = (now or utcnow()).astimezone(UTC)
    pending = list(
        session.scalars(
            select(Notification)
            .where(Notification.status.in_({"pending", "retry_wait"}))
            .order_by(Notification.created_at)
            .limit(settings.notification_batch_size)
        )
    )
    subscriptions = {
        _target_hash(subscription.email): subscription
        for subscription in session.scalars(
            select(Subscription).where(Subscription.enabled.is_(True))
        )
    }
    grouped: dict[str, list[Notification]] = defaultdict(list)
    for notification in pending:
        grouped[notification.target_hash].append(notification)

    sent = 0
    failed = 0
    deferred = 0
    for target_hash, notifications in grouped.items():
        subscription = subscriptions.get(target_hash)
        if subscription is None:
            _mark_failure(
                notifications,
                RuntimeError("Subscription is unavailable or disabled"),
            )
            failed += len(notifications)
            continue
        if subscription.frequency == "daily":
            if not _daily_is_due(subscription, current_time):
                deferred += len(notifications)
                continue
            reports = [
                report
                for notification in notifications
                if (report := session.get(Report, notification.report_id)) is not None
            ]
            if not reports:
                _mark_failure(notifications, RuntimeError("Queued reports are unavailable"))
                failed += len(notifications)
                continue
            subject, body = _daily_digest(reports, current_time)
            try:
                sender(settings, subscription.email, subject, body)
            except Exception as exc:
                _mark_failure(notifications, exc)
                failed += len(notifications)
            else:
                _mark_sent(notifications)
                subscription.last_sent_at = current_time
                sent += len(notifications)
            continue

        for notification in notifications:
            report = session.get(Report, notification.report_id)
            if report is None:
                _mark_failure([notification], RuntimeError("Queued report is unavailable"))
                failed += 1
                continue
            headline = str(report.content_json.get("headline") or report.event_id)
            try:
                sender(
                    settings,
                    subscription.email,
                    f"[News Claws] {headline}"[:998],
                    report.content_markdown,
                )
            except Exception as exc:
                _mark_failure([notification], exc)
                failed += 1
            else:
                _mark_sent([notification])
                subscription.last_sent_at = current_time
                sent += 1
    session.commit()
    return {
        "status": "completed",
        "sent": sent,
        "failed": failed,
        "deferred": deferred,
    }
