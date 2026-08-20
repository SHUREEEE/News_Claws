from datetime import UTC, datetime
from pathlib import Path

from news_claws.config import Settings
from news_claws.database import get_engine, session_factory
from news_claws.models import (
    AnalysisRun,
    Base,
    EventCluster,
    Industry,
    IndustryImpact,
    Notification,
    Report,
)
from news_claws.notifications import (
    create_subscription,
    dispatch_pending_notifications,
    queue_report_notifications,
)
from news_claws.schemas import SubscriptionCreate
from sqlalchemy import func, select


def _settings(database_url: str, project_root: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        admin_token="test-token",
        trendradar_mcp_url="http://127.0.0.1:3333/mcp",
        trendradar_enabled=False,
        search_provider="disabled",
        llm_provider="deterministic",
        llm_model="rules-v1",
        daily_llm_budget=1.0,
        data_retention_days=365,
        seed_demo=False,
        log_level="WARNING",
        allowed_hosts=("testserver",),
        max_request_bytes=1_048_576,
        scheduler_enabled=False,
        scheduler_interval_seconds=900,
        scheduler_max_items=20,
        outbound_user_agent="NewsClaws/0.1 (test suite)",
        project_root=project_root,
        notification_enabled=True,
        smtp_host="smtp.example.test",
        smtp_from="alerts@example.test",
        smtp_starttls=False,
    )


def _report(event_id: str, version: int = 1) -> Report:
    return Report(
        event_id=event_id,
        version=version,
        content_json={
            "headline": f"Policy event {version}",
            "summary": ["A verified policy update was published."],
        },
        content_markdown=f"# Policy event {version}",
        content_html=f"<h1>Policy event {version}</h1>",
        input_hash=str(version) * 64,
    )


def _impact(event_id: str, relevance: int) -> IndustryImpact:
    return IndustryImpact(
        event_id=event_id,
        industry_id="industry_test",
        relevance=relevance,
        direction="positive",
        strength="medium",
        horizon="quarters",
        mechanism="regulation",
        explanation="The policy directly affects the test industry.",
        confidence="high",
        evidence_ids=["ev_test"],
        analysis_run_id=f"analysis_{event_id}",
    )


def _event_and_run(event_id: str) -> tuple[EventCluster, AnalysisRun]:
    return (
        EventCluster(id=event_id, title=f"Event {event_id}"),
        AnalysisRun(
            id=f"analysis_{event_id}",
            event_id=event_id,
            stage="impact",
            model="rules-v1",
            prompt_version="test-v1",
            input_hash="a" * 64,
            output_json={},
        ),
    )


def test_notification_queue_is_thresholded_idempotent_and_dispatchable(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'notifications.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    settings = _settings(database_url, Path(__file__).resolve().parents[2])
    sent_messages: list[tuple[str, str, str]] = []

    def sender(_settings: Settings, recipient: str, subject: str, body: str) -> None:
        sent_messages.append((recipient, subject, body))

    with session_factory(database_url)() as session:
        session.add(Industry(id="industry_test", code="T", name="Test industry"))
        session.commit()
        create_subscription(
            session,
            SubscriptionCreate(
                email="ALERTS@company.org",
                industry_ids=["industry_test"],
                min_relevance=80,
                frequency="immediate",
            ),
        )
        report = _report("event_one")
        event, analysis_run = _event_and_run("event_one")
        session.add(event)
        session.commit()
        session.add(analysis_run)
        session.commit()
        session.add_all([report, _impact("event_one", 85)])
        session.commit()

        assert queue_report_notifications(session, report) == 1
        assert queue_report_notifications(session, report) == 0
        session.commit()
        notification = session.scalar(select(Notification))
        assert notification is not None
        assert "alerts@company.org" not in notification.idempotency_key
        assert len(notification.target_hash) == 64

        result = dispatch_pending_notifications(
            session,
            settings,
            sender=sender,
        )
        assert result == {
            "status": "completed",
            "sent": 1,
            "failed": 0,
            "deferred": 0,
        }
        assert sent_messages[0][0] == "alerts@company.org"
        assert "Policy event 1" in sent_messages[0][1]
        assert notification.status == "sent"


def test_daily_notifications_are_batched_and_failures_become_retryable(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'daily.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    settings = _settings(database_url, Path(__file__).resolve().parents[2])
    attempts = 0

    def failing_sender(
        _settings: Settings,
        _recipient: str,
        _subject: str,
        _body: str,
    ) -> None:
        nonlocal attempts
        attempts += 1
        raise OSError("SMTP unavailable")

    with session_factory(database_url)() as session:
        session.add(Industry(id="industry_test", code="T", name="Test industry"))
        session.commit()
        create_subscription(
            session,
            SubscriptionCreate(
                email="digest@company.org",
                min_relevance=50,
                frequency="daily",
                digest_hour_utc=8,
            ),
        )
        for index in (1, 2):
            event_id = f"event_{index}"
            report = _report(event_id, index)
            event, analysis_run = _event_and_run(event_id)
            session.add(event)
            session.commit()
            session.add(analysis_run)
            session.commit()
            session.add_all([report, _impact(event_id, 70)])
            session.commit()
            assert queue_report_notifications(session, report) == 1
            session.commit()

        deferred = dispatch_pending_notifications(
            session,
            settings,
            now=datetime(2026, 8, 20, 7, tzinfo=UTC),
            sender=failing_sender,
        )
        assert deferred["deferred"] == 2
        assert attempts == 0

        failed = dispatch_pending_notifications(
            session,
            settings,
            now=datetime(2026, 8, 20, 8, tzinfo=UTC),
            sender=failing_sender,
        )
        assert failed["failed"] == 2
        assert attempts == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(Notification.status == "retry_wait")
            )
            == 2
        )
