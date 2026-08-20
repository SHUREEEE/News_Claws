# Open Source And Content Boundaries

| Component | License | Boundary |
|---|---|---|
| TrendRadar | GPL-3.0 | Separate service; no copied source in `analysis-api`. |
| trendradar-mcp | Follow upstream repository | Separate adapter endpoint; version must be pinned before release. |
| RSSHub | AGPL-3.0 | Optional separate service for explicitly approved routes. |
| Newspaper4k | MIT | Optional in-process full-text adapter for allowed sources. |
| news-please | Apache-2.0 | Optional allow-listed site discovery, not enabled by default. |

This table is an engineering boundary, not legal advice. Before distribution or commercial use, re-check exact upstream versions, transitive dependencies, trademarks and source obligations.

Collection policy is source-specific. Prefer RSS, public APIs and sitemaps; honor terms, robots policy, rate limits and copyright. Never bypass login, CAPTCHA, paywalls or technical access restrictions. When full-text rights are unclear, retain metadata, a minimal evidence excerpt, hashes and the original link.
