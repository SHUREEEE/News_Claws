from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urljoin

import httpx
from news_claws.company_registry import upsert_sec_company_catalog
from news_claws.database import session_factory
from news_claws.domain.security import validate_public_http_url, validate_public_ip

DEFAULT_URL = "https://www.sec.gov/files/company_tickers.json"
MAX_CATALOG_BYTES = 20_000_000


def fetch_catalog(url: str, user_agent: str) -> dict:
    current_url = validate_public_http_url(url)
    with httpx.Client(headers={"User-Agent": user_agent}, trust_env=False, timeout=30) as client:
        for _redirect in range(4):
            with client.stream("GET", current_url, follow_redirects=False) as response:
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
                if declared_size > MAX_CATALOG_BYTES:
                    raise ValueError("SEC company catalog exceeds the 20 MB limit")
                payload = bytearray()
                for chunk in response.iter_bytes():
                    payload.extend(chunk)
                    if len(payload) > MAX_CATALOG_BYTES:
                        raise ValueError("SEC company catalog exceeds the 20 MB limit")
                parsed = json.loads(payload)
                if not isinstance(parsed, dict):
                    raise ValueError("SEC company catalog must be a JSON object")
                return parsed
    raise httpx.TooManyRedirects("SEC company catalog exceeded the redirect limit")


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize the SEC company/ticker catalog")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    user_agent = os.getenv("OUTBOUND_USER_AGENT", "").strip()
    if "@" not in user_agent or "example" in user_agent.lower():
        raise SystemExit("OUTBOUND_USER_AGENT must contain a real contact email")
    if args.limit is not None and not 1 <= args.limit <= 20_000:
        raise SystemExit("--limit must be between 1 and 20000")

    payload = (
        json.loads(args.fixture.read_text(encoding="utf-8"))
        if args.fixture
        else fetch_catalog(args.url, user_agent)
    )
    with session_factory()() as session:
        count = upsert_sec_company_catalog(session, payload, limit=args.limit)
    print(f"Synchronized {count} SEC companies")


if __name__ == "__main__":
    main()
