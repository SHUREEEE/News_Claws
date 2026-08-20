# News Claws Release Acceptance Matrix

Candidate date: 2026-08-20
Baselines: NC-PRD-001 V1.0 and the matching development design V1.0
Document state: both baselines are review drafts; product, technical, data/AI, and compliance approvers remain unassigned.

## Status Contract

- **PASS**: the repository implements the requirement and has repeatable automated evidence.
- **PARTIAL**: a useful implementation exists, but one or more acceptance clauses still need code, data, a live service, or human review.
- **OPEN**: a required implementation path is not present in the current candidate.
- **GATED**: completion depends on production infrastructure, credentials, a reviewed catalogue, a benchmark, or an authorized human decision.

Task-level PASS does not authorize merge, deployment, or production release. The release gate remains closed while any P0 item is OPEN or any required external approval is absent.

## Evidence Index

| Evidence | Location / command | Scope |
|---|---|---|
| E-API | `tests/integration/test_api.py` | UI/API security headers, reports, filters, source payload, event locking, audit, subscriptions |
| E-PIPE | `tests/integration/test_demo_pipeline.py` | deterministic end-to-end ingestion, versions, evidence, impact and reports |
| E-CLUSTER | `tests/integration/test_clustering.py` | event boundaries, data-domain separation and locked-cluster isolation |
| E-FILTER | `tests/integration/test_event_filters.py` | SQL-level language/source/industry/company/direction/strength filters before limit |
| E-SOURCE | `tests/unit/test_source_fallback.py`, `tests/unit/test_http_sources.py`, `tests/unit/test_rss.py` | RSS/API/Sitemap parsing, primary/fallback behavior, SSRF-safe failure |
| E-VERIFY | `tests/unit/test_verification.py`, `tests/unit/test_quality.py` | verification states, evidence conservatism and quality gates |
| E-NOTIFY | `tests/integration/test_notifications.py` | email queue, semantic deduplication and retry behavior |
| E-OPS | `tests/integration/test_backup_restore.py`, `tests/integration/test_migrations.py`, `tests/contracts/test_deployment_artifacts.py` | backup/restore, schema migration and deployment contracts |
| E-SEC | `tests/unit/test_security.py`, `tests/unit/test_production_env.py`, `tests/unit/test_public_smoke.py` | SSRF, production configuration and public smoke controls |
| E-RUN | `evidence/dev-local/run-log.md` and release-specific evidence directory | command results, browser evidence and sealed hashes |

## Product Goals

| ID | Acceptance summary | Status | Evidence / remaining gate |
|---|---|---|---|
| G-01 | Maintain 40-60 Chinese/English authoritative and official sources | PARTIAL | Catalogue size and fields are automated in E-PIPE; live pull reached 52/52 in the development run. Final country/agency catalogue and owners require product/compliance sign-off. |
| G-02 | Aggregate duplicate reports into events with manual correction | PASS | E-CLUSTER, E-PIPE and E-API cover deduplication, source chains, merge/split and lock behavior. |
| G-03 | Produce reviewable verification conclusions | PARTIAL | E-VERIFY and E-PIPE prove traceable rule-based conclusions. External evidence search and the human-reviewed verification benchmark are not complete. |
| G-04 | Produce industry and company impact summaries | PARTIAL | E-PIPE and E-FILTER prove the contract and deterministic output. Top-3/Top-5 precision on 200 human-reviewed events is GATED. |
| G-05 | Support browsing, filtering, notification, feedback and correction | PARTIAL | E-API and E-NOTIFY cover the local workflow. Live SMTP delivery and continuous trial operation are GATED. |

## P0 Functional Requirements

| ID | Status | Evidence / remaining work |
|---|---|---|
| FR-SRC-001 | PARTIAL | Source create/update/disable, connectivity tests and write audit exist (E-API); full UI editing of every policy field is not exposed. |
| FR-SRC-002 | PASS | RSS/Atom, API, Sitemap, manual URL and primary/fallback paths are covered by E-SOURCE. |
| FR-SRC-003 | PARTIAL | Official flag, owner, region and source type are stored; event detail does not yet present every official material subtype distinctly. |
| FR-SRC-004 | PARTIAL | Last success, failures and parse/HTTP diagnostics exist; automated disable recommendations are not implemented. |
| FR-ING-001 | PASS | Idempotent article/task behavior and retries are covered by E-PIPE and scheduler tests. |
| FR-ING-002 | PASS | Article/version models retain required metadata, canonical/original URLs, language, timestamps and hashes; missing values remain explicit. |
| FR-ING-003 | OPEN | Metadata/HTML parsing exists, but the configured Newspaper4k full-text path and source-level news-please discovery are not wired into collection. |
| FR-ING-004 | PASS | Version creation and changed-content traceability are covered by E-PIPE. |
| FR-EVT-001 | PASS | URL/hash/similarity deduplication is covered by E-CLUSTER and normalization tests. |
| FR-EVT-002 | PASS | Event membership, representative title, time and source counts are covered by E-PIPE and E-API. |
| FR-EVT-003 | PASS | Syndication/origin grouping and separate article/source-chain counts are covered by E-PIPE. |
| FR-EVT-004 | PASS | Merge/split reanalysis and lock isolation persist controlled actor/reason records; E-API and E-CLUSTER. |
| FR-VER-001 | PARTIAL | Structured current claims and quotes exist; opinion/prediction classification and the full maximum-three-claim contract need broader fixtures. |
| FR-VER-002 | PARTIAL | Ingested evidence is linked with stance and source chain; a configurable external search adapter is not implemented. |
| FR-VER-003 | PASS | Evidence quality, independence, conflicts, status and confidence explanations are covered by E-VERIFY. |
| FR-VER-004 | PASS | Reanalysis and report versions follow changed event evidence; E-PIPE and E-API. |
| FR-ANL-001 | PARTIAL | Target-specific direction is separated from company/industry impact; a complete target-level sentiment contract needs broader evaluation data. |
| FR-ANL-002 | PASS | Controlled Top-3 industries with relevance, direction, strength, mechanism, horizon, confidence and evidence are covered by E-PIPE. |
| FR-ANL-003 | PARTIAL | Names, aliases and tickers are supported; parent/subsidiary and brand relationships need reviewed production master data. |
| FR-ANL-004 | PASS | Relevance, strength and confidence are separate schema/UI/report fields; contract tests cover serialization. |
| FR-ANL-005 | PASS | Conservative rules and E-VERIFY prevent unsupported positive/negative conclusions. |
| FR-REP-001 | PASS | HTML, Markdown and JSON event reports share traceable data and safe templates; E-API and report contract tests. |
| FR-REP-002 | PARTIAL | API and dashboard cover most combined filters and stable query URLs; company selection and list export are not complete in the dashboard. |
| FR-REP-003 | PASS | Keyword/industry/company thresholds, semantic deduplication and repeat-on-material-change are covered by E-NOTIFY. |
| FR-REP-004 | PARTIAL | Email queue/retry is implemented; live SMTP is GATED. Feishu is not required if email is accepted as the one MVP channel. |
| FR-ADM-001 | PASS | Version-linked feedback accepts target, verdict, reason and actor; E-API. |
| FR-ADM-002 | PASS | Source writes, manual corrections, model/prompt versions, input hashes and analysis runs are traceable; E-API/E-PIPE. |
| FR-ADM-003 | PARTIAL | Environment validation, source schedule and budget settings exist; runtime UI/API changes for all thresholds/windows/retention are not implemented. |

## Non-Functional Requirements

| ID | Status | Evidence / remaining gate |
|---|---|---|
| NFR-PERF-001 | GATED | No verified 50k-article/10k-event P95 run; current functional tests do not substitute for the performance gate. |
| NFR-REL-001 | GATED | Local retries and job states exist, but >=99.0% monthly availability needs a live trial. |
| NFR-IDEM-001 | PASS | Article, task and notification idempotency are covered by E-PIPE/E-NOTIFY. |
| NFR-SEC-001 | PASS | Production secret validation and redaction boundaries are covered by E-SEC; real secrets remain external. |
| NFR-AUTH-001 | PASS | Bearer admin token protects management, analysis and feedback APIs; E-API. |
| NFR-COMP-001 | PARTIAL | Source policy fields and safe HTTP controls exist; robots/terms/copyright decisions for the final catalogue require compliance review. |
| NFR-LIC-001 | PARTIAL | Service boundaries and license notes are documented; commercial distribution requires a fresh dependency/legal review. |
| NFR-OBS-001 | PARTIAL | Source runs, audit logs, jobs and health are visible; production metrics/export and external alerting are not deployed. |
| NFR-I18N-001 | PASS | UTC-aware data and Chinese/English source/article handling are covered by models and E-PIPE. |
| NFR-A11Y-001 | PARTIAL | Semantic labels, focus styles and non-color status text exist; final keyboard/screen-reader review is required. |
| NFR-BACKUP-001 | PARTIAL | Consistent SQLite backup/restore is covered by E-OPS; daily scheduling and a timed production RTO drill are GATED. |
| NFR-COST-001 | PARTIAL | Daily budget configuration and deterministic zero-provider mode exist; per-event external provider accounting/automatic degradation is not proven. |

## UAT Scenarios

| ID | Status | Evidence / remaining work |
|---|---|---|
| UAT-01 | PASS | Synthetic official material plus independent coverage reaches original-material confirmation in E-PIPE. |
| UAT-02 | PASS | Single-source behavior remains reported rather than false; E-VERIFY. |
| UAT-03 | PARTIAL | Syndication grouping is proven with smaller deterministic fixtures; the exact 10-site/1-chain fixture is not present. |
| UAT-04 | PASS | Conflicting credible evidence maps to disputed with parallel evidence; E-VERIFY. |
| UAT-05 | PARTIAL | Article versioning is proven; an end-to-end corrected-number fixture with affected-claim timeline remains. |
| UAT-06 | PASS | Alias/ticker mapping and target roles are covered by alias tests and E-PIPE. |
| UAT-07 | PASS | The cloud-compliance demo produces negative cloud impact and positive compliance-service opportunity separately. |
| UAT-08 | PARTIAL | Timeout/MIME/size failures are safe and diagnostic in E-SOURCE; scheduler retry exhaustion/dead-state evidence needs a full scenario. |
| UAT-09 | OPEN | There is no external LLM JSON-contract retry/degrade adapter in the current deterministic candidate. |
| UAT-10 | PASS | Semantic notification deduplication and material-change resend behavior are covered by E-NOTIFY. |

## Release Gates

The repository can be treated as a local development candidate after the full verification gate passes. It is not a production release candidate until all of the following are resolved:

1. Product, technical, data/AI and compliance approvers are assigned and both review-draft baselines are signed.
2. FR-ING-003 and UAT-09 are implemented or explicitly removed from the approved MVP baseline.
3. The official source and exchange/company catalogues are reviewed, including a real SEC contact address and per-source compliance policy.
4. The fixed >=200-event human benchmark meets clustering and Top-N precision thresholds.
5. The 50k-article performance gate, two-week trial, accessibility review and production recovery drill pass.
6. A production host, domain, DNS/TLS, container runtime, secrets, SMTP settings and monitoring destination are supplied.
7. A release owner separately authorizes merge, deployment and public release after evidence sealing.
