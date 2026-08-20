from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def test_migrated_application_serves_ui_and_protected_api(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{(tmp_path / 'api.db').as_posix()}"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ADMIN_TOKEN", "integration-token")
    monkeypatch.setenv("SEED_DEMO", "true")

    from news_claws.config import get_settings
    from news_claws.database import get_engine

    get_settings.cache_clear()
    get_engine.cache_clear()
    main = importlib.import_module("news_claws.main")

    async def fake_manual_ingestion(_session, source, url, _settings):
        return {
            "source_id": source.id,
            "article_id": "art_manual",
            "event_id": "evt_manual",
            "report_id": "rpt_manual",
            "created": True,
            "http_status": 200,
            "url": url,
        }

    monkeypatch.setattr(main, "ingest_manual_url", fake_manual_ingestion)
    with TestClient(main.app) as client:
        assert client.get("/health/live").json()["status"] == "ok"
        assert client.get("/health/ready").json()["status"] == "ready"
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "最新事件" in dashboard.text
        assert "DEMO" in dashboard.text
        assert dashboard.headers["x-content-type-options"] == "nosniff"
        assert dashboard.headers["x-frame-options"] == "DENY"
        assert dashboard.headers["x-request-id"]
        app_js = client.get("/static/app.js")
        assert app_js.status_code == 200
        assert app_js.headers["content-type"].startswith("application/javascript")

        unauthorized = client.get("/api/v1/events")
        assert unauthorized.status_code == 401
        assert unauthorized.headers["content-type"].startswith("application/problem+json")

        headers = {"Authorization": "Bearer integration-token"}
        events = client.get("/api/v1/events", headers=headers)
        assert events.status_code == 200
        items = events.json()["items"]
        assert len(items) == 2
        detail = client.get(f"/api/v1/events/{items[0]['id']}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["evidence"]
        report_id = items[0]["report_id"]
        report = client.get(f"/api/v1/reports/{report_id}", headers=headers)
        assert report.status_code == 200
        assert report.json()["verification"]["supporting_evidence_ids"]
        html_report = client.get(
            f"/api/v1/reports/{report_id}?format=html",
            headers=headers,
        )
        assert html_report.status_code == 200
        assert '<link rel="stylesheet" href="/static/report.css">' in html_report.text
        assert "<style>" not in html_report.text

        updated = client.patch(
            "/api/v1/sources/us_sec_press",
            headers=headers,
            json={"enabled": False},
        )
        assert updated.status_code == 200
        assert updated.json()["enabled"] is False

        demo_update = client.patch(
            "/api/v1/sources/demo_market_daily",
            headers=headers,
            json={"enabled": False},
        )
        assert demo_update.status_code == 400

        source_test = client.post(
            "/api/v1/sources/demo_market_daily/test",
            headers=headers,
        )
        assert source_test.status_code == 200
        source_list = client.get("/api/v1/sources", headers=headers).json()
        demo_source = next(item for item in source_list if item["id"] == "demo_market_daily")
        assert demo_source["last_success_at"] is not None

        manual = client.post(
            "/api/v1/ingestion/url",
            headers=headers,
            json={
                "source_id": "us_federal_reserve",
                "url": "https://www.federalreserve.gov/newsevents/test.htm",
            },
        )
        assert manual.status_code == 201
        assert manual.json()["event_id"] == "evt_manual"

        rejected_manual = client.post(
            "/api/v1/ingestion/url",
            headers=headers,
            json={
                "source_id": "demo_market_daily",
                "url": "https://example.com/news",
            },
        )
        assert rejected_manual.status_code == 400

        subscription = client.post(
            "/api/v1/subscriptions",
            headers=headers,
            json={
                "email": "alerts@company.org",
                "min_relevance": 75,
                "frequency": "daily",
                "digest_hour_utc": 1,
            },
        )
        assert subscription.status_code == 201
        subscription_id = subscription.json()["id"]
        subscriptions = client.get("/api/v1/subscriptions", headers=headers)
        assert subscriptions.status_code == 200
        assert subscriptions.json()["items"][0]["email"] == "alerts@company.org"

        dispatch = client.post("/api/v1/notifications/dispatch", headers=headers)
        assert dispatch.status_code == 200
        assert dispatch.json()["status"] == "disabled"

        disabled = client.delete(
            f"/api/v1/subscriptions/{subscription_id}",
            headers=headers,
        )
        assert disabled.status_code == 204

        audit = client.get("/api/v1/audit-logs", headers=headers)
        assert audit.status_code == 200
        entries = audit.json()["items"]
        assert any(item["path"] == "/api/v1/sources/us_sec_press" for item in entries)
        assert all(len(item["client_hash"]) == 64 for item in entries)

        oversized = client.post(
            "/api/v1/feedback",
            headers=headers,
            content=b"x" * 1_048_577,
        )
        assert oversized.status_code == 413
        assert oversized.json()["code"] == "REQUEST_TOO_LARGE"

    get_settings.cache_clear()
    get_engine.cache_clear()
