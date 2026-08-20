import asyncio

import httpx
import pytest
from news_claws.adapters.http_sources import discover_site_entries


def test_site_discovery_stops_before_root_when_robots_disallows_it(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.http_sources.validate_public_http_url",
        lambda url: url,
    )
    requested_paths: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        assert request.url.path == "/robots.txt"
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"User-agent: *\nDisallow: /news\n",
        )

    with pytest.raises(ValueError, match="disallowed by robots.txt"):
        asyncio.run(
            discover_site_entries(
                "https://agency.example/news",
                source_id="agency_news",
                allowed_source_ids={"agency_news"},
                limit=2,
                user_agent="NewsClaws test",
                transport=httpx.MockTransport(responder),
            )
        )

    assert requested_paths == ["/robots.txt"]


def test_site_discovery_does_not_fetch_disallowed_article_paths(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.http_sources.validate_public_http_url",
        lambda url: url,
    )
    requested_paths: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"User-agent: *\nDisallow: /news/private\n",
            )
        assert request.url.path == "/news"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b'<html><body><a href="/news/private/release">private</a></body></html>',
        )

    with pytest.raises(ValueError, match="did not yield"):
        asyncio.run(
            discover_site_entries(
                "https://agency.example/news",
                source_id="agency_news",
                allowed_source_ids={"agency_news"},
                limit=2,
                user_agent="NewsClaws test",
                transport=httpx.MockTransport(responder),
            )
        )

    assert requested_paths == ["/robots.txt", "/news"]


def test_missing_robots_file_defaults_to_no_declared_restrictions(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.http_sources.validate_public_http_url",
        lambda url: url,
    )

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.path == "/news":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b'<html><body><a href="/news/release">release</a></body></html>',
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html><head><title>Release</title></head><body>article body</body></html>",
        )

    async def fake_fetch(url: str, *, user_agent: str, parser_name: str, transport):
        from news_claws.adapters.rss import FeedEntry

        return (
            FeedEntry(
                title="Release",
                url=url,
                summary="Summary",
                published_at=None,
                updated_at=None,
                author=None,
                body_excerpt="Article body",
                parse_diagnostics={"extractor": "news-please", "status": "succeeded"},
            ),
            200,
        )

    monkeypatch.setattr("news_claws.adapters.http_sources.fetch_html_entry", fake_fetch)

    entries, status = asyncio.run(
        discover_site_entries(
            "https://agency.example/news",
            source_id="agency_news",
            allowed_source_ids={"agency_news"},
            limit=1,
            user_agent="NewsClaws test",
            transport=httpx.MockTransport(responder),
        )
    )

    assert status == 200
    assert [entry.title for entry in entries] == ["Release"]
