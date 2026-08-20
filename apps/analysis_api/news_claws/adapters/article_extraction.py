from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from news_claws.domain.normalization import normalize_text


class ArticleExtractionError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractedArticle:
    extractor: str
    title: str
    text: str
    summary: str
    authors: tuple[str, ...]
    published_at: datetime | None
    canonical_url: str | None


def _newspaper_factory(url: str) -> Any:
    try:
        from newspaper import Article
    except ImportError as exc:
        raise ArticleExtractionError(
            "Newspaper4k is unavailable; install the project extract extra"
        ) from exc
    return Article(url, fetch_images=False)


def _newsplease_factory(html: str, url: str) -> Any:
    try:
        from newsplease import NewsPlease
    except ImportError as exc:
        raise ArticleExtractionError(
            "news-please is unavailable; install the project discover extra"
        ) from exc
    return NewsPlease.from_html(html, url=url, fetch_images=False)


def extract_with_newspaper4k(
    html: str,
    url: str,
    *,
    article_factory: Callable[[str], Any] | None = None,
) -> ExtractedArticle:
    article = (article_factory or _newspaper_factory)(url)
    try:
        article.download(input_html=html, ignore_read_more=True)
        article.parse()
    except Exception as exc:
        raise ArticleExtractionError("Newspaper4k could not parse the supplied HTML") from exc
    text = normalize_text(str(getattr(article, "text", "") or ""))
    if not text:
        raise ArticleExtractionError("Newspaper4k did not find usable article text")
    authors = tuple(
        value
        for item in (getattr(article, "authors", None) or [])
        if (value := normalize_text(str(item)))
    )
    return ExtractedArticle(
        extractor="newspaper4k",
        title=normalize_text(str(getattr(article, "title", "") or "")),
        text=text,
        summary=normalize_text(str(getattr(article, "meta_description", "") or "")),
        authors=authors,
        published_at=getattr(article, "publish_date", None),
        canonical_url=normalize_text(str(getattr(article, "canonical_link", "") or "")) or None,
    )


def extract_with_newsplease(
    html: str,
    url: str,
    *,
    article_factory: Callable[[str, str], Any] | None = None,
) -> ExtractedArticle:
    try:
        article = (article_factory or _newsplease_factory)(html, url)
    except ArticleExtractionError:
        raise
    except Exception as exc:
        raise ArticleExtractionError("news-please could not parse the supplied HTML") from exc
    if not article:
        raise ArticleExtractionError("news-please returned no article")
    text = normalize_text(str(getattr(article, "maintext", "") or ""))
    if not text:
        raise ArticleExtractionError("news-please did not find usable article text")
    authors = tuple(
        value
        for item in (getattr(article, "authors", None) or [])
        if (value := normalize_text(str(item)))
    )
    return ExtractedArticle(
        extractor="news-please",
        title=normalize_text(str(getattr(article, "title_page", "") or "")),
        text=text,
        summary=normalize_text(str(getattr(article, "description", "") or "")),
        authors=authors,
        published_at=getattr(article, "date_publish", None),
        canonical_url=normalize_text(str(getattr(article, "url", "") or "")) or None,
    )


def extract_article_html(
    html: str,
    url: str,
    *,
    parser: str = "auto",
    newspaper_factory: Callable[[str], Any] | None = None,
    newsplease_factory: Callable[[str, str], Any] | None = None,
) -> ExtractedArticle:
    if parser not in {"auto", "metadata", "newspaper4k", "news-please"}:
        raise ArticleExtractionError(f"Unsupported article parser: {parser}")
    if parser == "metadata":
        raise ArticleExtractionError("Source is configured for metadata-only parsing")
    if parser == "news-please":
        return extract_with_newsplease(html, url, article_factory=newsplease_factory)
    return extract_with_newspaper4k(html, url, article_factory=newspaper_factory)
