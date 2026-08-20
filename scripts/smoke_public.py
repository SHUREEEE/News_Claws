from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx


class SmokeFailure(RuntimeError):
    pass


def _expect(response: httpx.Response, status_code: int, label: str) -> None:
    if response.status_code != status_code:
        raise SmokeFailure(f"{label}: expected HTTP {status_code}, received {response.status_code}")


def _expect_header(
    response: httpx.Response,
    name: str,
    predicate: Callable[[str], bool],
    label: str,
) -> None:
    value = response.headers.get(name, "")
    if not predicate(value):
        raise SmokeFailure(f"{label}: invalid or missing {name} header")


def _json(response: httpx.Response, label: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SmokeFailure(f"{label}: response is not JSON") from exc
    if not isinstance(payload, dict):
        raise SmokeFailure(f"{label}: response must be a JSON object")
    return payload


def run_smoke(
    base_url: str,
    *,
    basic_user: str,
    basic_password: str,
    admin_token: str,
    transport: httpx.BaseTransport | None = None,
) -> list[str]:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        raise SmokeFailure("Base URL must be an HTTPS origin without a path")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise SmokeFailure("Base URL must not include credentials, query or fragment")
    if not basic_user or not basic_password or not admin_token:
        raise SmokeFailure("Basic-auth credentials and administrator token are required")

    origin = base_url.rstrip("/")
    checks: list[str] = []
    client_options: dict[str, Any] = {
        "base_url": origin,
        "follow_redirects": False,
        "timeout": 15,
        "transport": transport,
    }
    with httpx.Client(**client_options) as anonymous:
        live = anonymous.get("/health/live")
        _expect(live, 200, "anonymous liveness")
        if _json(live, "anonymous liveness").get("status") != "ok":
            raise SmokeFailure("anonymous liveness: service status is not ok")
        _expect_header(
            live,
            "strict-transport-security",
            lambda value: "max-age=" in value,
            "anonymous liveness",
        )
        checks.append("anonymous liveness")

        protected = anonymous.get("/")
        _expect(protected, 401, "whole-site authentication")
        _expect_header(
            protected,
            "www-authenticate",
            lambda value: value.lower().startswith("basic"),
            "whole-site authentication",
        )
        checks.append("whole-site authentication")

    with httpx.Client(
        **client_options,
        auth=httpx.BasicAuth(basic_user, basic_password),
    ) as authenticated:
        ready = authenticated.get("/health/ready")
        _expect(ready, 200, "authenticated readiness")
        if _json(ready, "authenticated readiness").get("status") != "ready":
            raise SmokeFailure("authenticated readiness: service status is not ready")
        checks.append("authenticated readiness")

        dashboard = authenticated.get("/")
        _expect(dashboard, 200, "authenticated dashboard")
        for name, expected in (
            ("x-content-type-options", "nosniff"),
            ("x-frame-options", "DENY"),
        ):
            _expect_header(
                dashboard,
                name,
                lambda value, expected=expected: value == expected,
                "authenticated dashboard",
            )
        _expect_header(
            dashboard,
            "content-security-policy",
            lambda value: "default-src 'self'" in value,
            "authenticated dashboard",
        )
        checks.append("authenticated dashboard and security headers")

        admin_required = authenticated.get("/api/v1/events?limit=1")
        _expect(admin_required, 401, "administrator token enforcement")
        checks.append("administrator token enforcement")

        admin_headers = {"X-Admin-Token": admin_token}
        events = authenticated.get("/api/v1/events?limit=1", headers=admin_headers)
        _expect(events, 200, "event API")
        if not isinstance(_json(events, "event API").get("items"), list):
            raise SmokeFailure("event API: items must be a list")
        checks.append("event API")

        subscriptions = authenticated.get("/subscriptions")
        _expect(subscriptions, 200, "subscriptions UI")
        if "订阅管理" not in subscriptions.text:
            raise SmokeFailure("subscriptions UI: expected page title is missing")
        checks.append("subscriptions UI")

        audit = authenticated.get("/api/v1/audit-logs?limit=1", headers=admin_headers)
        _expect(audit, 200, "audit API")
        if not isinstance(_json(audit, "audit API").get("items"), list):
            raise SmokeFailure("audit API: items must be a list")
        checks.append("audit API")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run read-only smoke checks against News Claws")
    parser.add_argument("base_url", help="Public HTTPS origin, e.g. https://news.company.org")
    args = parser.parse_args()
    try:
        checks = run_smoke(
            args.base_url,
            basic_user=os.getenv("BASIC_AUTH_USER", ""),
            basic_password=os.getenv("BASIC_AUTH_PASSWORD", ""),
            admin_token=os.getenv("ADMIN_TOKEN", ""),
        )
    except (httpx.HTTPError, SmokeFailure) as exc:
        raise SystemExit(f"Public smoke failed: {exc}") from exc
    print(f"Public smoke passed: {len(checks)} checks")
    for check in checks:
        print(f"- {check}")


if __name__ == "__main__":
    main()
