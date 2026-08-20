# News Claws Delivery State

- Release ID: `dev-local`
- Current loop: `L1 project / L2A task`
- Delivery path: `full`
- Current phase: `07 Verification / production release gate`
- Current work package: `WP-8 production release`
- Task state: `blocked`
- Task owner: `Maker (Codex)`
- Verification owner: `independent verification pass completed`
- Budget owner: `Tech Lead (user acting as project approver)`
- Evidence directory: `evidence/dev-local/`
- Last evidence: 83 tests and the full local gate passed; fresh replay eventually passed 52/52 sources and ingested 260 articles into 254 events with five exact-title cross-source clusters; the human benchmark remains absent
- Next step: obtain the external release inputs listed below, then publish, deploy and run public acceptance

## Authorization Envelope

| Field | Frozen value |
|---|---|
| Goal | Deliver and deploy the smallest complete News Claws MVP from ingestion to evidence-backed event reports and subscriptions. |
| Scope | Source registry, RSS/API/sitemap/HTML/manual ingestion, normalization/versioning, event clustering, claims/evidence, verification, industry/company impact, reports, company catalogs, subscriptions, notifications, feedback, health, security, deployment and rollback. |
| Non-scope | Auto-trading, paywall bypass, unrestricted crawling, probability-of-truth claims or price prediction. |
| Objects | Files under this repository, local test databases, and the production target once supplied by the owner. |
| Evidence | Automated tests, API responses, database state, report artifacts and Playwright screenshots. |
| Acceptance | P0 vertical flow works locally; evidence IDs are traceable; duplicate reposts do not count as independent sources; desktop/mobile UI is usable. |
| Risks | External source changes, copyright/robots rules, model hallucination, entity ambiguity, GPL/AGPL boundaries. |
| Forbidden | Fabricating credentials, contact identities, official datasets or benchmark labels; destructive database operations; bypassing access controls. |
| Stop conditions | Material scope change, separate authorization gate, critical evidence unknown, or the same root cause rejected three times. |

## Decisions And Unknowns

- Verified fact: the user explicitly authorized development from `NC-PRD-001` and `NC-TDD-001`.
- Decision: pending vendor, budget and compliance choices become runtime configuration and release gates; they do not block a local MVP.
- Decision: the MVP remains useful without a configured LLM/search vendor by using deterministic analysis and conservative verification states.
- Unknown: production source allow-list, commercial distribution model and final retention policy remain business decisions.

## Production Release Blockers

- No Git remote exists, so the verified revision cannot be pushed or merged remotely.
- No Linux host with Docker Engine/Compose has been supplied; Docker is not installed locally.
- No production domain, DNS control, TLS target or public endpoint exists.
- No production administrator secret, Caddy basic-auth hash or other deployment secrets exist.
- No real monitored contact email is available for SEC-compliant synchronization.
- No SMTP service, credentials or verified sender is available for real notification delivery.
- No reviewed official SSE/SZSE/HKEX exports have been supplied.
- No human-labeled benchmark of at least 200 real, non-demo events exists.

## State History

| Time | From | To | Trigger | Evidence |
|---|---|---|---|---|
| 2026-08-20 | `ready` | `in_progress` | User authorized implementation and the required baselines were readable. | `evidence/dev-local/run-log.md` |
| 2026-08-20 | `in_progress` | `passed` | WP-0 authorization, scope, decisions and ownership were persisted. | `PLAN.md`, `docs/adr/` |
| 2026-08-20 | `ready` | `in_progress` | WP-1 dependencies and DoD are available. | `apps/analysis_api/news_claws/models.py` |
| 2026-08-20 | in_progress | passed | WP-1 idempotent ingestion, article versioning and source-run persistence passed automated integration checks. | tests, run log |
| 2026-08-20 | ready | passed | WP-2 deterministic clustering, repost retention, independence grouping and merge/split contracts passed. | tests, services |
| 2026-08-20 | ready | passed | WP-3 claim/evidence traceability, conservative verification and evidence-ID whitelist passed. | tests, verification domain |
| 2026-08-20 | ready | passed | WP-4 industry/company relevance, direction, mechanism and evidence linkage passed. | tests, reports |
| 2026-08-20 | ready | passed | WP-5 dashboard, detail tabs, reports and feedback flow passed desktop/mobile browser checks. | Playwright evidence |
| 2026-08-20 | ready | passed | WP-6 auth, SSRF guard, health, migrations, backup/restore and Compose contracts passed. | tests, README |
| 2026-08-20 | ready | passed | WP-7 Checker pass: Ruff clean, 19 tests passed, domain branch coverage 89%, protected browser action 200, console clean, no desktop/mobile horizontal overflow. | final run log |
| 2026-08-20 | passed | in_progress | User expanded the objective to merge and deploy the completed local candidate. | active goal |
| 2026-08-20 | in_progress | blocked | Local release checks exposed missing external deployment inputs and the absent real 200-event quality benchmark. | `PLAN.md`, production blockers, run log |
| 2026-08-20 | passed | in_progress | Real-data audit reopened WP-2 after unrelated official releases were found in one event. | `evidence/dev-local/clustering-audit.md` |
| 2026-08-20 | in_progress | passed | Two minimal clustering repairs passed focused tests and a fresh 260-article replay. | `tests/integration/test_clustering.py`, clustering audit |
