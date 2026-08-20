from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from news_claws.adapters.article_extraction import (
    ArticleExtractionError,
    extract_with_newspaper4k,
    extract_with_newsplease,
)


def test_newspaper4k_parses_only_the_supplied_html() -> None:
    calls: dict[str, object] = {}

    class FakeArticle:
        title = "Extracted title"
        text = "Full article body"
        meta_description = "Extracted summary"
        authors = ["Reporter"]
        publish_date = datetime(2026, 8, 21, tzinfo=UTC)
        canonical_link = "https://agency.example/news/one"

        def download(self, *, input_html: str, ignore_read_more: bool) -> None:
            calls["html"] = input_html
            calls["ignore_read_more"] = ignore_read_more

        def parse(self) -> None:
            calls["parsed"] = True

    result = extract_with_newspaper4k(
        "<html><body>provided</body></html>",
        "https://agency.example/news/one",
        article_factory=lambda url: calls.setdefault("url", url) and FakeArticle(),
    )

    assert calls == {
        "url": "https://agency.example/news/one",
        "html": "<html><body>provided</body></html>",
        "ignore_read_more": True,
        "parsed": True,
    }
    assert result.extractor == "newspaper4k"
    assert result.text == "Full article body"
    assert result.authors == ("Reporter",)


def test_newspaper4k_failure_is_normalized_without_leaking_internal_details() -> None:
    class BrokenArticle:
        def download(self, *, input_html: str, ignore_read_more: bool) -> None:
            raise OSError("private filesystem detail")

    with pytest.raises(ArticleExtractionError, match="supplied HTML") as captured:
        extract_with_newspaper4k(
            "<html></html>",
            "https://agency.example/news/two",
            article_factory=lambda _url: BrokenArticle(),
        )

    assert "private filesystem" not in str(captured.value)


def test_newsplease_uses_the_supplied_html_adapter() -> None:
    captured: dict[str, str] = {}

    def factory(html: str, url: str) -> object:
        captured.update(html=html, url=url)
        return SimpleNamespace(
            maintext="News Please body",
            title_page="News Please title",
            description="Summary",
            authors=["Desk"],
            date_publish=None,
            url=url,
        )

    result = extract_with_newsplease(
        "<html>safe input</html>",
        "https://agency.example/news/three",
        article_factory=factory,
    )

    assert captured["html"] == "<html>safe input</html>"
    assert result.extractor == "news-please"
    assert result.text == "News Please body"
