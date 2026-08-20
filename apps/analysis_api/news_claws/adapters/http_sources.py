from __future__ import annotations

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import httpx

from news_claws.adapters.rss import FeedEntry, _parse_date
from news_claws.domain.normalization import normalize_text
from news_claws.domain.security import (
    UnsafeUrlError,
    validate_public_http_url,
    validate_public_ip,
)

MAX_SOURCE_BYTES = 2_000_000
MAX_REDIRECTS = 4
MAX_SITEMAP_FILES = 5


@dataclass(frozen=True)
class HttpPayload:
    body: bytes
    status_code: int
    final_url: str
    encoding: str


def _absolute_http_url(base_url: str, value: str) -> str:
    resolved = urljoin(base_url, value.strip())
    parts = urlsplit(resolved)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise UnsafeUrlError("Article URLs must be absolute http/https URLs without credentials")
    return resolved


def _content_encoding(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        name, separator, value = part.strip().partition("=")
        if separator and name.lower() == "charset":
            candidate = value.strip("\"' ")
            try:
                "".encode(candidate)
            except LookupError:
                break
            return candidate
    return "utf-8"


async def fetch_public_bytes(
    url: str,
    *,
    accepted_mime_fragments: tuple[str, ...],
    user_agent: str,
    timeout_seconds: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> HttpPayload:
    current_url = validate_public_http_url(url)
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        timeout=timeout_seconds,
        transport=transport,
        trust_env=False,
    ) as client:
        for _redirect in range(MAX_REDIRECTS):
            async with client.stream("GET", current_url, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                    current_url = validate_public_http_url(urljoin(current_url, location))
                    continue

                response.raise_for_status()
                network_stream = response.extensions.get("network_stream")
                if network_stream is not None:
                    server_address = network_stream.get_extra_info("server_addr")
                    if server_address:
                        validate_public_ip(server_address[0])

                content_length = response.headers.get("content-length", "0") or "0"
                try:
                    declared_size = int(content_length)
                except ValueError as exc:
                    raise ValueError("Source returned an invalid Content-Length") from exc
                if declared_size < 0 or declared_size > MAX_SOURCE_BYTES:
                    raise ValueError("Source exceeds the 2 MB safety limit")

                content_type = response.headers.get("content-type", "")
                mime = content_type.split(";", 1)[0].strip().lower()
                if mime and not any(fragment in mime for fragment in accepted_mime_fragments):
                    raise ValueError(f"Source returned an unsupported content type: {mime}")

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_SOURCE_BYTES:
                        raise ValueError("Source exceeds the 2 MB safety limit")
                return HttpPayload(
                    body=bytes(body),
                    status_code=response.status_code,
                    final_url=current_url,
                    encoding=_content_encoding(content_type),
                )
    raise httpx.TooManyRedirects("Source exceeded the redirect limit")


def _api_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "data", "articles", "entries"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    if payload and all(isinstance(item, dict) for item in payload.values()):
        return list(payload.values())
    return []


def parse_api_entries(payload: bytes, base_url: str, limit: int = 20) -> list[FeedEntry]:
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("API response is not valid JSON") from exc

    entries: list[FeedEntry] = []
    for item in _api_items(decoded):
        title = normalize_text(
            str(item.get("title") or item.get("headline") or item.get("name") or "")
        )
        raw_url = item.get("url") or item.get("link") or item.get("canonical_url")
        if not title or not isinstance(raw_url, str):
            continue
        try:
            article_url = _absolute_http_url(base_url, raw_url)
        except UnsafeUrlError:
            continue
        entries.append(
            FeedEntry(
                title=title,
                url=article_url,
                summary=normalize_text(
                    str(item.get("summary") or item.get("description") or item.get("excerpt") or "")
                ),
                published_at=_parse_date(
                    str(item.get("published_at") or item.get("published") or item.get("date") or "")
                ),
                updated_at=_parse_date(str(item.get("updated_at") or item.get("updated") or "")),
                author=normalize_text(str(item.get("author") or "")) or None,
                origin_url=(
                    _absolute_http_url(base_url, str(item["origin_url"]))
                    if item.get("origin_url")
                    else None
                ),
            )
        )
        if len(entries) >= limit:
            break
    return entries


async def fetch_api_entries(
    url: str,
    *,
    limit: int,
    user_agent: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[FeedEntry], int]:
    response = await fetch_public_bytes(
        url,
        accepted_mime_fragments=("json",),
        user_agent=user_agent,
        transport=transport,
    )
    entries = parse_api_entries(response.body, response.final_url, limit)
    if not entries:
        raise ValueError("API response did not contain any usable news entries")
    return entries, response.status_code


class _NewsHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self.canonical_url: str | None = None
        self._inside_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "title":
            self._inside_title = True
        elif tag.lower() == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content")
            if key and content and key not in self.metadata:
                self.metadata[key] = content
        elif tag.lower() == "link":
            rel = (values.get("rel") or "").lower().split()
            if "canonical" in rel and values.get("href"):
                self.canonical_url = values["href"]

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self._title_parts.append(data)

    @property
    def title(self) -> str:
        return normalize_text(
            self.metadata.get("og:title")
            or self.metadata.get("twitter:title")
            or " ".join(self._title_parts)
        )


def parse_html_entry(payload: bytes, url: str, encoding: str = "utf-8") -> FeedEntry:
    try:
        html = payload.decode(encoding, errors="replace")
    except LookupError:
        html = payload.decode("utf-8", errors="replace")
    parser = _NewsHtmlParser()
    parser.feed(html)
    if not parser.title:
        raise ValueError("HTML page does not contain a usable title")

    canonical_url = _absolute_http_url(url, parser.canonical_url) if parser.canonical_url else url
    metadata = parser.metadata
    return FeedEntry(
        title=parser.title,
        url=canonical_url,
        summary=normalize_text(
            metadata.get("og:description")
            or metadata.get("twitter:description")
            or metadata.get("description")
            or ""
        ),
        published_at=_parse_date(
            metadata.get("article:published_time")
            or metadata.get("date")
            or metadata.get("datepublished")
        ),
        updated_at=_parse_date(
            metadata.get("article:modified_time") or metadata.get("datemodified")
        ),
        author=normalize_text(metadata.get("author") or "") or None,
    )


async def fetch_html_entry(
    url: str,
    *,
    user_agent: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[FeedEntry, int]:
    response = await fetch_public_bytes(
        url,
        accepted_mime_fragments=("html", "xhtml"),
        user_agent=user_agent,
        transport=transport,
    )
    return (
        parse_html_entry(
            response.body,
            response.final_url,
            response.encoding,
        ),
        response.status_code,
    )


def parse_sitemap_urls(payload: bytes) -> tuple[str, list[str]]:
    declaration_probe = payload[:4096].upper()
    if b"<!DOCTYPE" in declaration_probe or b"<!ENTITY" in declaration_probe:
        raise ValueError("Sitemap XML declarations cannot contain DOCTYPE or ENTITY")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("Sitemap XML is invalid") from exc
    kind = root.tag.rsplit("}", 1)[-1]
    if kind not in {"urlset", "sitemapindex"}:
        raise ValueError("Sitemap root must be urlset or sitemapindex")
    urls = [
        normalize_text(node.text)
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "loc" and node.text
    ]
    return kind, urls


async def fetch_sitemap_entries(
    url: str,
    *,
    limit: int,
    user_agent: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[FeedEntry], int]:
    root_response = await fetch_public_bytes(
        url,
        accepted_mime_fragments=("xml", "text/plain"),
        user_agent=user_agent,
        transport=transport,
    )
    kind, urls = parse_sitemap_urls(root_response.body)
    article_urls: list[str] = []
    if kind == "urlset":
        article_urls = urls[:limit]
    else:
        for sitemap_url in urls[:MAX_SITEMAP_FILES]:
            child_response = await fetch_public_bytes(
                _absolute_http_url(root_response.final_url, sitemap_url),
                accepted_mime_fragments=("xml", "text/plain"),
                user_agent=user_agent,
                transport=transport,
            )
            child_kind, child_urls = parse_sitemap_urls(child_response.body)
            if child_kind != "urlset":
                continue
            article_urls.extend(child_urls[: limit - len(article_urls)])
            if len(article_urls) >= limit:
                break

    entries: list[FeedEntry] = []
    for article_url in article_urls[:limit]:
        try:
            entry, _status = await fetch_html_entry(
                _absolute_http_url(root_response.final_url, article_url),
                user_agent=user_agent,
                transport=transport,
            )
        except (httpx.HTTPError, UnsafeUrlError, ValueError):
            continue
        entries.append(entry)
    if not entries:
        raise ValueError("Sitemap did not yield any usable news pages")
    return entries, root_response.status_code
