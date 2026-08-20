from __future__ import annotations

import base64

import httpx
import pytest

from scripts.smoke_public import SmokeFailure, run_smoke

SECURITY_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'self'; object-src 'none'",
}


def _gateway(request: httpx.Request) -> httpx.Response:
    basic = "Basic " + base64.b64encode(b"newsadmin:secret").decode("ascii")
    is_authenticated = request.headers.get("authorization") == basic
    if request.url.path == "/health/live":
        return httpx.Response(200, json={"status": "ok"}, headers=SECURITY_HEADERS)
    if not is_authenticated:
        return httpx.Response(401, headers={"www-authenticate": 'Basic realm="restricted"'})
    if request.url.path == "/health/ready":
        return httpx.Response(200, json={"status": "ready"}, headers=SECURITY_HEADERS)
    if request.url.path == "/":
        return httpx.Response(200, text="<title>News Claws</title>", headers=SECURITY_HEADERS)
    if request.url.path == "/subscriptions":
        return httpx.Response(200, text="<title>订阅管理</title>", headers=SECURITY_HEADERS)
    if request.url.path.startswith("/api/v1/"):
        if request.headers.get("x-admin-token") != "admin-secret":
            return httpx.Response(401, json={"code": "HTTP_401"})
        return httpx.Response(200, json={"items": []}, headers=SECURITY_HEADERS)
    return httpx.Response(404)


def test_public_smoke_covers_gateway_and_application_authentication() -> None:
    checks = run_smoke(
        "https://news.company.org",
        basic_user="newsadmin",
        basic_password="secret",
        admin_token="admin-secret",
        transport=httpx.MockTransport(_gateway),
    )

    assert checks == [
        "anonymous liveness",
        "whole-site authentication",
        "authenticated readiness",
        "authenticated dashboard and security headers",
        "administrator token enforcement",
        "event API",
        "subscriptions UI",
        "audit API",
    ]


@pytest.mark.parametrize(
    "base_url",
    [
        "http://news.company.org",
        "https://news.company.org/path",
        "https://user:password@news.company.org",
        "https://news.company.org?debug=true",
    ],
)
def test_public_smoke_rejects_non_production_origins(base_url: str) -> None:
    with pytest.raises(SmokeFailure, match="Base URL"):
        run_smoke(
            base_url,
            basic_user="newsadmin",
            basic_password="secret",
            admin_token="admin-secret",
            transport=httpx.MockTransport(_gateway),
        )


def test_public_smoke_fails_on_missing_security_headers() -> None:
    def insecure_gateway(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health/live":
            return httpx.Response(200, json={"status": "ok"})
        return _gateway(request)

    with pytest.raises(SmokeFailure, match="strict-transport-security"):
        run_smoke(
            "https://news.company.org",
            basic_user="newsadmin",
            basic_password="secret",
            admin_token="admin-secret",
            transport=httpx.MockTransport(insecure_gateway),
        )
