import asyncio

import httpx
import pytest
from news_claws.adapters.rss import MAX_FEED_BYTES, fetch_feed, parse_feed


def test_parse_rss_and_atom_without_inventing_missing_fields() -> None:
    rss = b"""<?xml version="1.0"?><rss><channel><item>
      <title>Policy update</title><link>https://example.com/policy</link>
      <description>Official summary</description><pubDate>Wed, 20 Aug 2025 01:00:00 GMT</pubDate>
    </item></channel></rss>"""
    entries = parse_feed(rss)
    assert len(entries) == 1
    assert entries[0].title == "Policy update"
    assert entries[0].author is None
    assert entries[0].published_at is not None


def test_parse_atom_href_link() -> None:
    atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Central bank statement</title><link href="https://example.com/statement" />
      <summary>Statement summary</summary><updated>2026-08-20T01:00:00Z</updated>
    </entry></feed>"""
    entries = parse_feed(atom)
    assert entries[0].url == "https://example.com/statement"
    assert entries[0].published_at is None
    assert entries[0].updated_at is not None


def test_parse_feed_rejects_dtd_and_invalid_xml() -> None:
    with pytest.raises(ValueError, match="DOCTYPE"):
        parse_feed(b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss>&x;</rss>')
    with pytest.raises(ValueError, match="invalid"):
        parse_feed(b"<rss><broken></rss>")


def test_fetch_feed_streams_with_a_hard_size_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.rss.validate_public_http_url",
        lambda url: url,
    )

    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "application/rss+xml"},
                content=b"x" * (MAX_FEED_BYTES + 1),
            )
        )
        with pytest.raises(ValueError, match="2 MB"):
            await fetch_feed("https://feed.example.test/rss", transport=transport)

    asyncio.run(scenario())


def test_fetch_feed_rejects_non_feed_content_type(monkeypatch) -> None:
    monkeypatch.setattr(
        "news_claws.adapters.rss.validate_public_http_url",
        lambda url: url,
    )

    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<html>not a feed</html>",
            )
        )
        with pytest.raises(ValueError, match="unsupported content type"):
            await fetch_feed("https://feed.example.test/rss", transport=transport)

    asyncio.run(scenario())
