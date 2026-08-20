# News Claws Implementation Plan

This plan implements `NC-PRD-001` and `NC-TDD-001` using the full-risk Loop Engineering path. A task moves to `passed` only after repeatable verification; a failed check returns only to the smallest phase that can change the result.

## Dependency DAG

```text
WP-0 baseline
  -> WP-1 ingestion + persistence
     -> WP-2 event clustering
        -> WP-3 claims + evidence + verification
           -> WP-4 industry/company impact
              -> WP-5 reports + UI + feedback
                    -> WP-6 operations + security
                    -> WP-7 integration + browser acceptance
                       -> WP-8 production release
```

## Work Packages

| ID | State | Deliverable | Definition of done | Failure route |
|---|---|---|---|---|
| WP-0 | `passed` | Repository skeleton, contracts, ADRs and governance ledger | Baselines and non-scope are explicit; dependencies and ownership are recorded. | 01/03 if scope or architecture is unclear |
| WP-1 | `passed` | Source registry, RSS/fixture ingestion, normalized articles and versions | Idempotent ingestion tests pass; missing content is represented, not invented. | 05 for defects; 03 for contract problems |
| WP-2 | `passed` | Duplicate/syndication detection and event clusters | Reposts remain articles but share one independence group; merge/split contracts exist. | 05 for scoring defect; 04 if task boundary expands |
| WP-3 | `passed` | Claims, evidence, verification versions and ID whitelist | All verification statuses have evidence; unknown independence never counts as corroboration. | 05 for implementation defects; 01 for invalid acceptance rule |
| WP-4 | `passed` | Target sentiment and Top-3/Top-5 impacts | Relevance, strength and confidence remain separate; each impact has a mechanism and evidence IDs. | 05 for implementation defects; 03 for schema defects |
| WP-5 | `passed` | Event dashboard/detail, filters, sources, feedback and HTML/Markdown/JSON reports | A user can inspect an event from summary to evidence and submit feedback. | 02 for workflow defects; 05 for implementation defects |
| WP-6 | `passed` | Authentication, health, SSRF guard, logs, backup and Compose | Admin writes require a token; unsafe fetch targets are rejected; local runbook works. | 03 for security boundary defects; 05 otherwise |
| WP-7 | `passed` | Unit, integration, contract, golden and browser evidence | Automated suite passes; desktop and mobile screenshots have no blank or overlapping primary content. | Return to the smallest failed work package |
| WP-8 | `blocked` | Merge, deploy, public acceptance and rollback evidence | Published revision runs behind HTTPS; production data gates and public desktop/mobile smoke pass; rollback is verified. | 01 for missing authorization/input; 06-07 for deployment defects |

## Integration Order

Single working tree and single active implementation session are used for this local MVP. Integration order is the DAG above. `STATE.md` is updated serially; no child process or background service may edit it.

## Verification Summary

- Static quality: Ruff format and lint passed after the latest source, notification, quality-gate and MIME changes.
- Automated verification: the latest full gate is recorded in `evidence/dev-local/run-log.md`; domain branch coverage remains above the 85% gate.
- Runtime verification: Alembic reached `c31e8f2407ad (head)`; production-mode local health, authentication, subscriptions, disabled notification dispatch and audit logging passed against an isolated SQLite database.
- Live-source verification: 51 of 52 enabled non-demo sources passed from this network (98.1%); one UK feed timed out transiently.
- Browser verification: `/subscriptions` passed at 1440x900 and 390x844 with no horizontal overflow or clipped controls; company search, create and disable flows passed; console errors and warnings are zero.
- Release-quality verification: demo and unknown events are rejected. The gate is correctly blocked because no real 200-event human benchmark exists.

## Release Gate

The local implementation is a completion candidate. WP-8 remains blocked by missing Git remote, Linux/Docker target, domain/DNS, production secrets, real contact email, SMTP configuration, reviewed official exchange files and a real 200-event benchmark. These inputs must not be fabricated.
