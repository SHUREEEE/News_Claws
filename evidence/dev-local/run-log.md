# Development Run Log

## 2026-08-20 - Baseline Gate

- Evidence class: verified fact
- Read `NewsClaws_产品需求规格说明书_v1.0.docx`, including all tables.
- Read `NewsClaws_开发设计说明书_v1.0.docx`, including all tables.
- Read the Loop Engineering V2.2 visible rules, all eight phase definitions, risk routing, hierarchy and governance state machines.
- Confirmed full-risk path because the MVP changes data, API, security and compliance boundaries.
- Confirmed no source code existed before this run; the two Word files were untracked user artifacts.
- DOCX visual rendering could not run because LibreOffice is not installed. Structured DOCX parsing succeeded; this is a tooling limitation, not a product blocker.

Next evidence target: runnable application skeleton and persistence contract.
## 2026-08-20 - Build Evidence

- Evidence class: verified fact.
- Implemented the local Python 3.12/FastAPI/SQLAlchemy/Alembic MVP across WP-1 through WP-6.
- Persisted sources, source runs, article versions, syndication links, event clusters, claims, evidence, verification versions, industry/company impacts, reports, feedback and jobs.
- Implemented RSS/Atom collection with redirect revalidation, public-IP enforcement and a 2 MB response ceiling.
- Implemented deterministic clustering, repost independence grouping, conservative verification and strict evidence-ID report validation.
- Implemented HTML/Markdown/JSON reports, authenticated APIs, dashboard/detail/source/system views, feedback, merge/split and reanalysis.
- Added Docker/Compose, migrations, backup/restore scripts, README and GPL/AGPL service-boundary documentation.
- Demo events and companies are synthetic and visibly labeled DEMO.

## 2026-08-20 - Checker And Repair Loop

| Root cause ID | Checker result | Smallest return | Repair count | Final evidence |
|---|---|---|---:|---|
| NC-UI-001 | Internal English enums and legacy rationale appeared in the Chinese UI. | Phase 05 presentation/generation text only. | 1 | Chinese status, confidence, direction, strength, role, stance, mechanism and rationale confirmed in browser snapshots. |
| NC-HEALTH-001 | Never-run sources were counted and displayed as healthy. | Phase 05 health query/template only. | 1 | Dashboard reports 0/9 before live success; source rows show 未验证; failed-without-success has a distinct branch. |
| NC-BROWSER-001 | Missing favicon produced one console 404; token input produced a verbose form-semantic message. | Phase 05 routes/base template only. | 1 | Fresh browser session reports 0 console messages. |

No root cause reached the three-return stop condition.

## 2026-08-20 - Final Verification

- ruff format: clean after one formatting pass.
- ruff check: passed.
- pytest with isolated workspace temp directory: 19 passed, 2 dependency/runtime warnings.
- Domain branch coverage: 89% overall (normalization 89%, security 85%, verification 90%).
- Application startup: Alembic upgrade succeeded; readiness endpoint and UI served at http://127.0.0.1:8000.
- Authentication: browser token storage succeeded; protected demo source test returned HTTP 200 and 来源正常，读取 0 条样本.
- Browser console: 0 messages, 0 errors, 0 warnings in a fresh session.
- Desktop viewport: 1440x900; dashboard and event detail scrollWidth equals clientWidth.
- Mobile viewport: 390x844; dashboard and event detail scrollWidth equals clientWidth.
- Evidence screenshots:
  - output/playwright/final-dashboard-desktop.png
  - output/playwright/final-event-desktop.png
  - output/playwright/final-dashboard-mobile.png
  - output/playwright/final-event-mobile.png
- Structured browser snapshots confirm tab switching and Chinese labels for verification, impact, company role and evidence stance.
- The screenshot files were generated successfully by Playwright. The separate local image-view helper could not reopen browser-generated files because its Windows ACL setup failed; DOM dimensions, accessibility snapshots and the earlier visual review remain the layout evidence.

## Constraints And Residual Risk

- Verified fact: the environment could not resolve www.sec.gov; the SEC source test returned a 502 with Source host cannot be resolved: www.sec.gov. This is recorded as an external DNS limitation, not parser success.
- Unknown: other live-source availability, rate limits and feed changes require validation in the deployment network.
- Unknown: the production source allow-list, commercial distribution mode and retention period require owner/compliance decisions.
- Decision: no deployment, credentials, Git publication, real notification delivery or production database operation was performed.
- Decision: TrendRadar/RSSHub remain separately deployed services to preserve GPL/AGPL boundaries.

## Closeout Result

- Task result: passed for the local MVP completion candidate.
- Authorized scope completed: yes.
- Production release authorized: no.
- Runtime resource disposition: local development server intentionally left available for user acceptance; Playwright sessions are closed after evidence sealing.

## 2026-08-20 - Release Candidate Expansion

- Evidence class: verified fact.
- Added API/sitemap/HTML/manual-URL ingestion, SEC and official exchange company catalog importers, secure ticker aliases, subscriptions, notification queuing/dispatch, SMTP validation, audit coverage and the `/subscriptions` UI.
- Expanded the catalog to 56 sources: 53 non-demo definitions and 52 enabled non-demo sources across CN, EU, GLOBAL, HK, JP, UK and US.
- Alembic upgraded an isolated production-mode database to `c31e8f2407ad (head)`.
- Production-mode local smoke passed: liveness 200 with HSTS, unauthenticated subscription API 401, authenticated source count 52, subscription create/list/disable, disabled notification dispatch with zero sends, and admin audit records.

## 2026-08-20 - Release Checker And Repair Loop

| Root cause ID | Checker result | Smallest return | Repair count | Final evidence |
|---|---|---|---:|---|
| NC-QUALITY-001 | Unknown or demo event IDs could be represented as empty predictions and potentially satisfy a fabricated quality set. | Phase 05 quality loader and focused tests. | 1 | Unknown IDs and demo events now raise; 3 focused quality tests pass. |
| NC-MIME-001 | Windows served `app.js` as `text/plain`, so Chromium refused to execute subscriptions code. | Phase 05 static MIME registration and API integration assertion. | 1 | `app.js` returns `application/javascript`; integration test and fresh browser flow pass. |
| NC-SOURCE-001 | First 52-source check reached only 90.4% due one DNS failure and four transient timeouts. | Phase 07 failed-source recheck only. | 1 | All five failed sources passed on bounded recheck; complete rerun passed 51/52 (98.1%). |

No root cause reached the three-return stop condition.

## 2026-08-20 - Current Verification

- Final full gate: 59 tests passed with warnings treated as errors; domain branch coverage was 89.06% against an 85% minimum.
- Ruff format/check, Python compileall and `node --check app.js` passed.
- `pip-audit` found no known dependency vulnerabilities; the local `news-claws` package is not published on PyPI and was skipped as expected.
- Live-source gate: 51/52 enabled non-demo sources passed (98.1%); one UK Health feed timed out.
- Quality release gate: failed closed because `data/quality-labels.jsonl` does not exist. Demo and unknown database events are now explicitly rejected.
- Browser: company search requested `/api/v1/catalog/companies?q=Apple&limit=12` and returned 200; an industry subscription was created and disabled through the UI.
- Desktop: 1440x900, document scroll width 1440, no horizontal overflow.
- Mobile: 390x844 viewport, document scroll width 390, zero clipped controls.
- Browser console: 0 errors and 0 warnings after the MIME repair.
- Screenshots: `output/playwright/subscriptions-desktop.png` is 1440x900 and `subscriptions-mobile.png` is 390x1448; both have non-zero pixel variance.

## Production Release Status

- Local implementation candidate: passed.
- Production release: blocked.
- Blocking inputs: Git remote, Linux/Docker target, domain/DNS, production secrets, real contact email, SMTP configuration, reviewed official exchange files and a human-labeled 200-event benchmark.
- These inputs were not fabricated. Public HTTPS, real notification delivery, production data migration, rollback and post-deploy browser smoke remain pending.
