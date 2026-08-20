import asyncio
from types import SimpleNamespace

import httpx
import pytest
from news_claws import services
from news_claws.domain.security import UnsafeUrlError
from news_claws.models import Source


def _source(method: str, *, fallback_url: str | None = "https://fallback.example/news") -> Source:
    return Source(
        id=f"source_{method}",
        name=f"Source {method}",
        owner="Test publisher",
        region="US",
        language="en",
        source_type="government",
        tier="T1",
        official=True,
        method=method,
        entry_url="https://primary.example/news",
        fallback_url=fallback_url,
    )


@pytest.mark.parametrize(
    ("method", "fetcher_name"),
    [("rss", "fetch_feed"), ("api", "fetch_api_entries"), ("sitemap", "fetch_sitemap_entries")],
)
def test_primary_failure_uses_configured_fallback(
    monkeypatch, method: str, fetcher_name: str
) -> None:
    calls: list[str] = []

    async def fake_fetcher(url: str, **_kwargs):
        calls.append(url)
        if url == "https://primary.example/news":
            raise httpx.ConnectError("primary unavailable")
        return ["fallback-entry"], 200

    monkeypatch.setattr(services, fetcher_name, fake_fetcher)
    settings = SimpleNamespace(outbound_user_agent="NewsClaws test")

    entries, status = asyncio.run(services._fetch_source_entries(_source(method), settings, 5))

    assert entries == ["fallback-entry"]
    assert status == 200
    assert calls == ["https://primary.example/news", "https://fallback.example/news"]


def test_primary_failure_without_fallback_is_reraised(monkeypatch) -> None:
    async def fail(_url: str, **_kwargs):
        raise httpx.ReadTimeout("primary timed out")

    monkeypatch.setattr(services, "fetch_feed", fail)
    settings = SimpleNamespace(outbound_user_agent="NewsClaws test")

    with pytest.raises(httpx.ReadTimeout, match="primary timed out"):
        asyncio.run(services._fetch_source_entries(_source("rss", fallback_url=None), settings, 5))


def test_unsafe_primary_url_is_not_masked_by_fallback(monkeypatch) -> None:
    calls: list[str] = []

    async def reject_unsafe(url: str, **_kwargs):
        calls.append(url)
        if url == "https://primary.example/news":
            raise UnsafeUrlError("resolved to a private address")
        return ["must-not-run"], 200

    monkeypatch.setattr(services, "fetch_feed", reject_unsafe)
    settings = SimpleNamespace(outbound_user_agent="NewsClaws test")

    with pytest.raises(UnsafeUrlError, match="private address"):
        asyncio.run(services._fetch_source_entries(_source("rss"), settings, 5))

    assert calls == ["https://primary.example/news"]
