import asyncio
from types import SimpleNamespace

import pytest
from news_claws.adapters.rss import FeedEntry
from news_claws.schemas import SourceCreate
from news_claws.services import _enrich_source_entry


def _entry() -> FeedEntry:
    return FeedEntry(
        title="Feed title",
        url="https://agency.example/news/one",
        summary="Feed summary",
        published_at=None,
        updated_at=None,
        author=None,
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(outbound_user_agent="NewsClaws test")


def test_metadata_only_source_skips_article_fetch(monkeypatch) -> None:
    async def forbidden_fetch(*args, **kwargs):
        raise AssertionError("metadata-only sources must not fetch article pages")

    monkeypatch.setattr("news_claws.services.fetch_html_entry", forbidden_fetch)
    source = SimpleNamespace(content_policy="metadata_only", parser="auto")

    result = asyncio.run(_enrich_source_entry(source, _entry(), _settings()))

    assert result.title == "Feed title"
    assert result.parse_diagnostics == {"extractor": "metadata", "status": "skipped"}


def test_source_parser_override_is_forwarded_to_article_fetch(monkeypatch) -> None:
    captured: dict[str, str] = {}
    extracted = FeedEntry(
        title="Extracted title",
        url="https://agency.example/news/canonical",
        summary="Extracted summary",
        published_at=None,
        updated_at=None,
        author="Reporter",
        body_excerpt="Extracted body",
        parse_diagnostics={"extractor": "news-please", "status": "succeeded"},
    )

    async def fake_fetch(url: str, *, user_agent: str, parser_name: str):
        captured.update(url=url, user_agent=user_agent, parser_name=parser_name)
        return extracted, 200

    monkeypatch.setattr("news_claws.services.fetch_html_entry", fake_fetch)
    source = SimpleNamespace(content_policy="metadata_and_excerpt", parser="news-please")

    result = asyncio.run(_enrich_source_entry(source, _entry(), _settings()))

    assert captured["parser_name"] == "news-please"
    assert result.url == "https://agency.example/news/canonical"
    assert result.body_excerpt == "Extracted body"


def test_enrichment_failure_preserves_feed_title_url_and_error(monkeypatch) -> None:
    async def broken_fetch(url: str, *, user_agent: str, parser_name: str):
        raise ValueError("article parser failed")

    monkeypatch.setattr("news_claws.services.fetch_html_entry", broken_fetch)
    source = SimpleNamespace(content_policy="metadata_and_excerpt", parser="newspaper4k")

    result = asyncio.run(_enrich_source_entry(source, _entry(), _settings()))

    assert result.title == "Feed title"
    assert result.url == "https://agency.example/news/one"
    assert result.parse_diagnostics == {
        "extractor": "newspaper4k",
        "status": "failed",
        "error": "article parser failed",
    }


def test_website_source_requires_explicit_newsplease_and_excerpt_policy() -> None:
    payload = {
        "id": "agency_website",
        "name": "Agency website",
        "owner": "Agency",
        "region": "US",
        "language": "en",
        "tier": "S1",
        "official": True,
        "method": "website",
        "entry_url": "https://agency.example/news",
        "content_policy": "metadata_and_excerpt",
    }
    with pytest.raises(ValueError, match="parser=news-please"):
        SourceCreate.model_validate(payload)
    payload["parser"] = "news-please"
    assert SourceCreate.model_validate(payload).method == "website"
    payload["content_policy"] = "metadata_only"
    with pytest.raises(ValueError, match="excerpt-enabled"):
        SourceCreate.model_validate(payload)
