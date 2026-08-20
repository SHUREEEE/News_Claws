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

## 2026-08-20 - Production Artifact Hardening

- Evidence class: verified fact.
- Fixed non-root container ownership for both `/data` and `/backups`.
- Added immutable Git SHA image tagging and executable same-schema rollback commands.
- Changed Compose from whole-file environment injection to per-service variables. Caddy receives only `DOMAIN`, `BASIC_AUTH_USER` and `BASIC_AUTH_HASH`; it no longer receives the application administrator token or SMTP password.
- Production environment parsing now preserves single-quoted bcrypt dollar signs, rejects duplicate/unbalanced entries, constrains the SQLite path to `/data`, and validates gateway credentials, booleans and runtime numeric ranges before startup.
- Added `scripts/smoke_public.py`, a read-only HTTPS smoke covering anonymous liveness, whole-site Basic Auth, readiness, security headers, administrator-token enforcement, events, subscriptions and audit APIs.
- CI now enforces Ruff formatting, warnings-as-errors tests, JavaScript syntax and non-root data/backup write access inside the built image.
- Final local gate: 73 tests passed; domain branch coverage 89.06%; Ruff format/check, compileall, JavaScript syntax and dependency audit passed.
- The placeholder production template failed validation for the expected five unresolved release values.
- Limitation: Docker is not installed in this environment, so actual image build and Compose rendering remain CI/deployment-host checks.

## 2026-08-20 - Real-Data Clustering Repair

- Evidence class: verified fact.
- A real event incorrectly combined an ONS labour-market release with a CMA road-fuel-market release. The stored title Jaccard score was 0.214 against the previous 0.20 live threshold.
- WP-2 returned to Phase 05. Live automatic clustering now requires 0.72 similarity, matches only active and unlocked events in the same live/demo data domain, and uses a symmetric seven-day candidate window.
- The first fresh 52-source replay ingested 260 articles. Its all-cluster audit exposed a second defect: standalone one-digit dates were discarded, making separate EBA and DfE dated alerts appear identical.
- Standalone numbers are now retained as tokens. Focused clustering, demo-pipeline and normalization verification passed 15 tests; Ruff passed.
- The second fresh replay initially passed 50/52 sources. One OPSS transient failure and one SEC DNS failure both passed on one bounded retry, yielding 52/52 eventual success and 260 articles.
- The repaired dataset contains 254 events and five multi-article events. All five have identical titles across two or more configured sources. The ONS/CMA pair, four EBA alerts and two DfE updates each have distinct event IDs.
- SQLite `PRAGMA integrity_check` returned `ok`.
- Decision: this replay is regression and source-connectivity evidence only. It is not substituted for the required 200-event human-reviewed quality benchmark.

| Root cause ID | Checker result | Smallest return | Repair count | Final evidence |
|---|---|---|---:|---|
| NC-CLUSTER-001 | A 0.20 title threshold admitted low-information overlap and did not isolate live/demo candidate domains. | Phase 05 cluster candidate policy and focused tests. | 1 | Known unrelated titles are separate; legitimate near-duplicate and demo fixtures still cluster. |
| NC-CLUSTER-002 | The tokenizer discarded standalone one-digit dates, causing dated alert collisions. | Phase 05 token extraction and two focused tests. | 1 | EBA 3/5/6 August and DfE 5/19 August remain distinct in the fresh replay. |
| NC-FORMAT-001 | The first final gate found mixed formatting in three patched Python files. | Phase 05 formatter on the three named files only. | 1 | Final full gate reports 65 files formatted and Ruff clean. |
| NC-MIGRATION-001 | Alembic CLI ignored `DATABASE_URL`, so a successful command could migrate the default database instead of the requested target. | Phase 05 Alembic environment override and one subprocess integration test. | 1 | Explicit target reached `c31e8f2407ad`; target integrity is `ok`. |

No root cause reached the three-return stop condition.

## 2026-08-20 - Post-Repair Candidate Verification

- Evidence class: verified fact.
- Full pytest gate with warnings treated as errors: 83 passed.
- Domain branch coverage: 89.06% against the 85% minimum.
- Ruff format check: 65 files already formatted.
- Ruff lint, Python compileall and JavaScript syntax checks: passed.
- Dependency audit: no known vulnerabilities; the unpublished local `news-claws` package was skipped as expected.
- Fresh isolated Alembic upgrade honored `DATABASE_URL`, reached `c31e8f2407ad`, and passed `PRAGMA integrity_check`.
- Docker image build and in-container non-root mountpoint checks remain unexecuted because Docker is not installed locally.

## 2026-08-20 - Specification Completion Pass

- Evidence class: verified fact.
- Audited all 5 product goals, 28 P0 functional requirements, 12 non-functional requirements and 10 UAT scenarios from both Word baselines.
- Added `docs/RELEASE_ACCEPTANCE_MATRIX.md` with per-requirement PASS/PARTIAL/OPEN/GATED evidence and explicit release gates. Both source documents remain review drafts with all four approvers unassigned.
- Added primary/fallback collection for RSS/Atom, API and Sitemap sources. Unsafe primary or fallback targets fail closed and are never masked by a secondary URL.
- Moved verification, region, language, source, industry, company, direction and strength filtering into SQL before `limit`; API result metadata now returns sorted languages and source IDs.
- Added event lock/unlock API and UI controls. Lock changes persist actor/reason records, inactive events reject lock changes, and locked events are excluded from automatic clustering.
- Exposed fallback URL, timezone, compliance notes and contact owner in the authenticated source API contract.
- Corrected the malformed dashboard heading element and expanded the filter layout responsively.

### Checker And Repair Evidence

| Root cause ID | Checker result | Smallest return | Repair count | Final evidence |
|---|---|---|---:|---|
| NC-FALLBACK-001 | `UnsafeUrlError` inherits `ValueError`, so a broad catch could mask an unsafe primary URL with a fallback request. | Phase 05 source fallback exception routing. | 1 | Five fallback tests cover RSS/API/Sitemap, no-fallback propagation and unsafe-primary fail-closed behavior. |
| NC-FILTER-001 | Post-query Python filters could discard matches after the database had already applied `limit`. | Phase 05 event query construction. | 1 | SQL filtering before limit passes service and authenticated API integration tests. |
| NC-UI-TEMPLATE-001 | The dashboard heading `<section>` was missing its closing `>`. | Phase 05 dashboard template only. | 1 | Jinja rendering and desktop/mobile Playwright snapshots pass. |
| NC-FORMAT-001 | The final sorting patch had not been passed through Ruff format. | Phase 05 formatter on `services.py` only. | 2 cumulative | Second full gate reports 68 files already formatted and Ruff clean. |

No root cause reached the three-return stop condition.

### Final Verification Evidence

- Targeted regression: 13 tests passed for source fallback, filters, clustering and API behavior.
- Full pytest gate with warnings treated as errors: 90 passed.
- Domain branch coverage: 89.06% against the 85% minimum.
- Ruff format: 68 files already formatted; Ruff lint passed.
- Python compileall and `node --check apps/analysis_api/news_claws/static/app.js`: passed.
- Dependency audit: no known vulnerabilities; the unpublished local package was skipped as expected.
- Fresh isolated migration reached `c31e8f2407ad (head)`.
- Desktop dashboard: 1440x1000 screenshot, complete filter controls and correct event table.
- Mobile dashboard: 390x844 viewport, document width equals viewport width, zero horizontally overflowing elements and zero overlapping interactive-control pairs.
- Real-browser workflow: industry `isic_3510` returned the wind event; lock and unlock both persisted and re-rendered the correct button/banner state.
- Browser screenshots:
  - `output/playwright/dashboard-desktop.png`
  - `output/playwright/dashboard-mobile.png`
- Temporary `newsqa` browser, attachment browser, 8016 QA server and the prior 8015 preview were closed before sealing.

### Remaining Release Gates

- Verified fact: local code and integration gates pass.
- Unknown/GATED at that checkpoint: public deployment still lacked repository integration, a Linux/Docker host, domain/DNS/TLS, production secrets, a real SEC contact address, SMTP configuration, reviewed exchange catalogues, 50k performance evidence and a human-reviewed 200-event benchmark. The following 2026-08-21 entry supersedes the repository-integration portion only.
- Decision: deterministic local analysis remains the approved no-vendor MVP path. Broader PRD clauses for Newspaper4k/news-please and external LLM invalid-JSON recovery remain explicit acceptance gaps, not fabricated successes.

## 2026-08-21 - GitHub Integration And Deployment Governance

- Evidence class: verified fact.
- The repository is public at `SHUREEEE/News_Claws`; release `v0.1.1` and its SHA-tagged GHCR image were published and independently verified.
- PR #5 merged the protected production deployment workflow into `master` at `54be2efd594e4592caa3eb40f7eb5d4192ca2161`.
- Local verification passed 103 tests with warnings treated as errors and 89.06% domain branch coverage. Ruff format/lint, compileall, JavaScript syntax, YAML parsing, migrations and dependency audit passed.
- GitHub branch-push, pull-request and final `master` CI passed. Ubuntu CI additionally passed Bash syntax, Docker image build and non-root data/backup mount checks.
- The GitHub `production` environment was created with required reviewer `SHUREEEE`, a custom branch policy allowing only `master`, zero variables and zero secrets.
- The workflow validates a full lowercase master SHA, resolves and rechecks the OCI digest, pins SSH host verification, validates the complete production environment, requires an online SQLite backup before replacement, waits for readiness, runs public HTTPS smoke and only performs automatic rollback after explicit schema-compatibility approval.
- The two Word baselines, all tables, the release matrix and Loop Engineering V2.2 visible workflow were re-read for a completion audit. LibreOffice remains unavailable, so DOCX visual re-rendering could not be repeated; structured DOCX parsing succeeded.

### Current Release Decision

- Resolved: Git remote, repository publication, PR integration, immutable container publication, protected deployment workflow and GitHub production environment.
- Still GATED: FR-ING-003 and UAT-09 baseline decisions, real host/domain/DNS/TLS, production environment values and credentials, real contact identity, SMTP/monitoring, reviewed source/company catalogues, 200-event human benchmark, 50k performance run, two-week trial, timed recovery drill, accessibility review and four-role sign-off.
- Decision: no production deployment was dispatched and no missing input was fabricated. WP-8 remains `blocked` until the release owner supplies and approves the external inputs.

## 2026-08-21 - Ingestion And Strict LLM Closeout

- Evidence class: verified local fact.
- Wired Newspaper4k extraction and explicit news-please website discovery into safe collection; third-party libraries receive only already-fetched HTML.
- Added source parser persistence/migration, metadata-only skip, bounded enrichment concurrency, same-origin discovery and robots-aware filtering.
- Added strict OpenAI-compatible JSON Schema analysis with one repair, evidence/target allow-lists, prompt bounds, token/cost accounting, dead/retry states and explicit manual retry.
- Repaired duplicate targets, non-finite numeric validation, failed-call budget accounting and merge/split post-commit response semantics during the Checker loop.
- Final local gate passed 146 tests with warnings treated as errors and 89.88% domain branch coverage; Ruff format/lint and compileall passed.
- Real Newspaper4k/news-please HTML smoke, dependency audit and isolated migration to `d542a38f7c10 (head)` passed.
- Detailed evidence and remaining GitHub/production gates: `evidence/dev-local/ingestion-llm-closeout-20260821.md`.
