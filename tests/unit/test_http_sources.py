import asyncio

import httpx
import pytest
from news_claws.adapters.http_sources import (
    MAX_SOURCE_BYTES,
    fetch_api_entries,
    fetch_public_bytes,
    fetch_sitemap_entries,
    parse_api_entries,
    parse_html_entry,
    parse_sitemap_urls,
)


def test_parse_api_entries_supports_common_news_fields() -> None:
    payload = b"""{
      "articles": [
        {
          "headline": "Regulator publishes final rule",
          "url": "/news/final-rule",
          "description": "The rule takes effect next quarter.",
          "published_at": "2026-08-20T02:00:00Z",
          "author": "Policy Office"
        },
        {"title": "Unsafe", "url": "javascript:alert(1)"}
      ]
    }"""

    entries = parse_api_entries(payload, "https://agency.example/api/news")

    assert len(entries) == 1
    assert entries[0].url == "https://agency.example/news/final-rule"
    assert entries[0].published_at is not None
    assert entries[0].author == "Policy Office"


def test_parse_api_entries_rejects_invalid_json() -> None:
    with pytest.raises(ValueError, match="valid JSON"):
        parse_api_entries(b"{broken", "https://agency.example/api")


def test_parse_html_entry_uses_metadata_and_canonical_url() -> None:
    payload = b"""<html><head>
      <title>Fallback title</title>
      <meta property="og:title" content="Official policy update">
      <meta name="description" content="A short official summary">
      <meta property="article:published_time" content="2026-08-20T03:00:00Z">
      <link rel="canonical" href="/news/policy-update">
    </head></html>"""

    entry = parse_html_entry(payload, "https://agency.example/news?id=4")

    assert entry.title == "Official policy update"
    assert entry.url == "https://agency.example/news/policy-update"
    assert entry.summary == "A short official summary"
    assert entry.published_at is not None


def test_parse_sitemap_urls_rejects_dtd_and_invalid_roots() -> None:
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_sitemap_urls(b"<!DOCTYPE urlset><urlset />")
    with pytest.raises(ValueError, match="root"):
        parse_sitemap_urls(b"<feed />")


def test_fetch_api_entries_enforces_mime_and_size(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.http_sources.validate_public_http_url",
        lambda url: url,
    )

    async def scenario() -> None:
        wrong_mime = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"{}",
            )
        )
        with pytest.raises(ValueError, match="content type"):
            await fetch_api_entries(
                "https://agency.example/api",
                limit=3,
                user_agent="NewsClaws test",
                transport=wrong_mime,
            )

        oversized = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "application/json"},
                content=b"x" * (MAX_SOURCE_BYTES + 1),
            )
        )
        with pytest.raises(ValueError, match="2 MB"):
            await fetch_public_bytes(
                "https://agency.example/api",
                accepted_mime_fragments=("json",),
                user_agent="NewsClaws test",
                transport=oversized,
            )

    asyncio.run(scenario())


def test_fetch_sitemap_discovers_and_parses_news_pages(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.http_sources.validate_public_http_url",
        lambda url: url,
    )

    def responder(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sitemap.xml":
            return httpx.Response(
                200,
                headers={"content-type": "application/xml"},
                content=b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                  <url><loc>https://agency.example/news/one</loc></url>
                </urlset>""",
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><head><title>News one</title></head></html>",
        )

    async def scenario() -> None:
        entries, status = await fetch_sitemap_entries(
            "https://agency.example/sitemap.xml",
            limit=3,
            user_agent="NewsClaws test",
            transport=httpx.MockTransport(responder),
        )
        assert status == 200
        assert [entry.title for entry in entries] == ["News one"]

    asyncio.run(scenario())
