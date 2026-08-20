# Open Source And Content Boundaries

| Component | License | Boundary |
|---|---|---|
| TrendRadar | GPL-3.0 | Separate service; no copied source in `analysis-api`. |
| trendradar-mcp | Follow upstream repository | Separate adapter endpoint; version must be pinned before release. |
| RSSHub | AGPL-3.0 | Optional separate service for explicitly approved routes. |
| Newspaper4k | MIT | In-process extraction from HTML already fetched by the SSRF-safe client; its downloader and optional NLP features are not used. |
| news-please | Apache-2.0 | In-process parsing for explicitly allow-listed website sources; its crawler/downloader is not used. |

This table is an engineering boundary, not legal advice. Before distribution or commercial use, re-check exact upstream versions, transitive dependencies, trademarks and source obligations.

Collection policy is source-specific. Prefer RSS, public APIs and sitemaps; honor terms, robots policy, rate limits and copyright. Never bypass login, CAPTCHA, paywalls or technical access restrictions. When full-text rights are unclear, retain metadata, a minimal evidence excerpt, hashes and the original link.

The production image installs the `extract` and `discover` extras so configured parsers fail diagnostically rather than silently disappearing. Website discovery remains disabled until a source ID is placed in `NEWS_PLEASE_DISCOVERY_SOURCE_IDS`; it fetches only same-origin HTML, checks `robots.txt` before the root page and each candidate, and treats robots errors other than 404/410 as collection failures.

Installed dependency verification on 2026-08-21 used Newspaper4k 0.9.6 and news-please 1.6.16. `pip-audit` reported no known vulnerabilities in the resolved environment; the unpublished local `news-claws` package was the only expected unaudited item. Version ranges remain in `pyproject.toml`, so every release build must repeat the audit.
