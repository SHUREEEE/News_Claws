import asyncio

import httpx
import pytest
from news_claws.adapters.article_extraction import ExtractedArticle
from news_claws.adapters.http_sources import discover_site_entries, parse_same_site_links


def test_same_site_link_discovery_deduplicates_and_excludes_assets() -> None:
    payload = b"""<html><body>
      <a href="/news/one#section">one</a>
      <a href="https://agency.example/news/one">duplicate</a>
      <a href="/assets/photo.jpg">image</a>
      <a href="https://outside.example/news/two">outside</a>
      <a href="http://agency.example/news/downgrade">scheme downgrade</a>
      <a href="https://agency.example:bad/news/invalid">bad port</a>
    </body></html>"""

    assert parse_same_site_links(payload, "https://agency.example/news") == [
        "https://agency.example/news/one"
    ]


def test_newsplease_site_discovery_requires_source_allowlist(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.http_sources.validate_public_http_url",
        lambda url: url,
    )

    async def scenario() -> None:
        with pytest.raises(ValueError, match="allow-listed"):
            await discover_site_entries(
                "https://agency.example/news",
                source_id="agency_news",
                allowed_source_ids=set(),
                limit=3,
                user_agent="NewsClaws test",
                transport=httpx.MockTransport(
                    lambda _request: pytest.fail("network must not run before allowlist check")
                ),
            )

    asyncio.run(scenario())


def test_allowlisted_site_discovery_fetches_only_same_site_html(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.http_sources.validate_public_http_url",
        lambda url: url,
    )
    parser_calls: list[tuple[str, str]] = []

    def extract(html: str, url: str, parser: str) -> ExtractedArticle:
        parser_calls.append((url, parser))
        return ExtractedArticle(
            extractor="news-please",
            title="Discovered official release",
            text="A discovered article body.",
            summary="Discovery summary",
            authors=(),
            published_at=None,
            canonical_url=url,
        )

    monkeypatch.setattr("news_claws.adapters.http_sources.extract_article_html", extract)
    requested_paths: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content=b"User-agent: *\nAllow: /\n",
            )
        if request.url.path == "/news":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=b"""<html><body>
                  <a href="/news/release-one">release</a>
                  <a href="https://outside.example/news/release-two">outside</a>
                </body></html>""",
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><head><title>Release</title></head><body>body</body></html>",
        )

    async def scenario() -> None:
        entries, status = await discover_site_entries(
            "https://agency.example/news",
            source_id="agency_news",
            allowed_source_ids={"agency_news"},
            limit=2,
            user_agent="NewsClaws test",
            transport=httpx.MockTransport(responder),
        )
        assert status == 200
        assert len(entries) == 1
        assert entries[0].title == "Discovered official release"
        assert entries[0].parse_diagnostics["status"] == "succeeded"

    asyncio.run(scenario())
    assert requested_paths == ["/robots.txt", "/news", "/news/release-one"]
    assert parser_calls == [("https://agency.example/news/release-one", "news-please")]
