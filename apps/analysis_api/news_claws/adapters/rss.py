from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx

from news_claws.domain.normalization import normalize_text
from news_claws.domain.security import validate_public_http_url, validate_public_ip

MAX_FEED_BYTES = 2_000_000


@dataclass(frozen=True)
class FeedEntry:
    title: str
    url: str
    summary: str
    published_at: datetime | None
    updated_at: datetime | None
    author: str | None
    origin_url: str | None = None
    body_excerpt: str = ""
    parse_diagnostics: dict[str, Any] = field(default_factory=dict)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _first_text(node: ElementTree.Element, names: tuple[str, ...]) -> str:
    for child in list(node):
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name in names and child.text:
            return normalize_text(child.text)
    return ""


def parse_feed(
    payload: bytes,
    limit: int = 20,
    *,
    base_url: str | None = None,
) -> list[FeedEntry]:
    declaration_probe = payload[:4096].upper()
    if b"<!DOCTYPE" in declaration_probe or b"<!ENTITY" in declaration_probe:
        raise ValueError("Feed XML declarations cannot contain DOCTYPE or ENTITY")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise ValueError("Feed XML is invalid") from exc
    candidates = root.findall(".//item")
    if not candidates:
        candidates = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "entry"]
    entries: list[FeedEntry] = []
    for node in candidates[:limit]:
        title = _first_text(node, ("title",))
        summary = _first_text(node, ("description", "summary", "content"))
        author = _first_text(node, ("author", "creator")) or None
        published = _first_text(node, ("pubDate", "published", "issued", "date"))
        updated = _first_text(node, ("updated", "modified"))
        link = _first_text(node, ("link",))
        if not link:
            for child in list(node):
                if child.tag.rsplit("}", 1)[-1] == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        if not link:
            link = _first_text(node, ("guid",))
        if title and link:
            resolved_link = urljoin(base_url, link) if base_url else link
            entries.append(
                FeedEntry(
                    title=title,
                    url=resolved_link,
                    summary=summary,
                    published_at=_parse_date(published),
                    updated_at=_parse_date(updated),
                    author=author,
                )
            )
    return entries


async def fetch_feed(
    url: str,
    limit: int = 20,
    timeout_seconds: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
    user_agent: str = "NewsClaws/0.1 (local development)",
) -> tuple[list[FeedEntry], int]:
    current_url = validate_public_http_url(url)
    headers = {"User-Agent": user_agent}
    async with httpx.AsyncClient(
        timeout=timeout_seconds,
        headers=headers,
        transport=transport,
        trust_env=False,
    ) as client:
        for _redirect in range(4):
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

                declared_size = int(response.headers.get("content-length", "0") or 0)
                if declared_size > MAX_FEED_BYTES:
                    raise ValueError("Feed exceeds the 2 MB safety limit")

                content_type = response.headers.get("content-type", "")
                mime = content_type.split(";", 1)[0].strip().lower()
                if mime and "xml" not in mime and mime != "text/plain":
                    raise ValueError(f"Feed returned an unsupported content type: {mime}")

                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_FEED_BYTES:
                        raise ValueError("Feed exceeds the 2 MB safety limit")
                return (
                    parse_feed(bytes(payload), limit=limit, base_url=current_url),
                    response.status_code,
                )
    raise httpx.TooManyRedirects("Feed exceeded the redirect limit")
