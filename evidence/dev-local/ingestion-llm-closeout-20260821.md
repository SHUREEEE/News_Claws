# Ingestion And LLM Gap Closeout Evidence

Date: 2026-08-21
Branch: `codex/close-ingestion-llm-gaps`
Evidence class: verified local fact unless explicitly marked pending or gated.

## Implemented Boundaries

- Newspaper4k parses only HTML already fetched by the SSRF-safe client. Feed/API metadata and diagnostics survive extraction failure; `metadata_only` skips article retrieval.
- news-please parses only safely fetched HTML. `website` collection requires `parser=news-please`, an excerpt-enabled policy and an exact `NEWS_PLEASE_DISCOVERY_SOURCE_IDS` allow-list entry.
- Website discovery checks `robots.txt` before the root request and before each same-origin candidate. A missing 404/410 file means no declared restriction; other robots retrieval failures stop collection.
- OpenAI-compatible analysis requests strict JSON Schema output. Evidence, industry and company IDs are server allow-listed; duplicate targets are rejected; one repair call is permitted.
- A second invalid schema creates a dead job and failed analysis run without a valid report. Provider failures enter `retry_wait`; explicit reanalysis can retry a dead job.
- Prompts are bounded to 12 evidence records, 24 industries, 12 companies, three aliases per company and 6,000 event-text characters, with per-field truncation below the 40,000-character message contract.
- Successful and contract-invalid calls persist token counts and estimated costs. Non-finite prices/budgets are rejected; failed calls with usage metadata consume the daily budget.
- Merge/split commits are reported independently from follow-up model analysis status, so a model failure cannot imply an already committed event correction was rolled back.

## Dependency And Runtime Evidence

- Installed `newspaper4k 0.9.6` and `news-please 1.6.16` from `.[dev,extract,discover]`.
- Real-library local HTML smoke extracted 157 body characters with both libraries. Newspaper4k emitted only its expected optional-NLP warning; the application does not call those NLP features.
- `pip-audit` reported no known vulnerabilities. The unpublished local `news-claws` distribution was skipped as expected.
- An isolated empty SQLite database upgraded through every migration to `d542a38f7c10 (head)`.
- Local Docker CLI/Engine is unavailable. GitHub Actions supplied the Docker build, push and immutable digest verification evidence after merge.

## Final Local Gate

```text
Ruff format: 88 files already formatted
Ruff lint: All checks passed
Python compileall: passed
Pytest: 146 passed with warnings treated as errors
Domain branch coverage: 89.88% (minimum 85%)
Focused hardening: 25 passed
Robots/prompt boundary: 7 passed
git diff --check: passed (line-ending notices only)
```

## Checker And Repair Loop

| Root cause ID | Checker result | Smallest return | Repair count | Final evidence |
|---|---|---|---:|---|
| NC-LLM-DUP-001 | Duplicate model target IDs could reach database unique constraints. | Domain output validation and focused tests. | 1 | Duplicate targets require repair; repaired output succeeds. |
| NC-LLM-COST-001 | Contract-invalid calls did not persist token/cost usage, weakening the daily budget. | Contract error metadata and failed analysis-run persistence. | 1 | Two invalid calls persist summed tokens and cost; full suite passes. |
| NC-LLM-NUM-001 | NaN/Infinity could bypass comparison-only runtime checks. | Runtime model, adapter and production preflight validation. | 1 | Non-finite budgets, timeout and prices are rejected. |
| NC-LLM-PROMPT-001 | Industry catalog growth could exceed the 40k message contract. | Candidate selection and per-field bounds. | 1 | A 100-extra-industry fixture remains bounded and succeeds. |
| NC-MUTATION-001 | Merge/split could commit and then return 502 on model failure. | Post-commit analysis result contract. | 1 | APIs return committed event plus `succeeded`, `dead` or `retry_wait`. |
| NC-ROBOTS-001 | Allow-listed website discovery did not enforce documented robots policy. | Safe HTTP adapter and website discovery tests. | 1 | Disallowed roots/candidates are never fetched; 404 behavior is explicit. |
| NC-ORIGIN-001 | Same-site discovery compared host and port but could accept an HTTPS-to-HTTP downgrade. | Require identical scheme, host and port; add a downgrade regression fixture. | 1 | Six discovery/robots tests and the 146-test full suite pass. |

No root cause reached the Loop three-return stop condition.

## GitHub Release Evidence

- PR [#7](https://github.com/SHUREEEE/News_Claws/pull/7) merged into `master` at `2092bd1761450d2bf6cbb1aba1a1d4429fb9cdbc` after all branch and pull-request checks passed.
- Final `master` CI run [32428038226](https://github.com/SHUREEEE/News_Claws/actions/runs/32428038226) completed successfully for the merge SHA.
- Container publication run [32428170485](https://github.com/SHUREEEE/News_Claws/actions/runs/32428170485) completed successfully, including `Verify immutable image digest`.
- Published image: `ghcr.io/shureeee/news_claws:2092bd1761450d2bf6cbb1aba1a1d4429fb9cdbc`.
- Verified OCI digest: `sha256:f77477f2adb950527a10ea138d298664d826d1713c5973c6353079755cd2bd5a`.

## Remaining Release Gates

- Passed GitHub evidence: branch CI, draft PR CI, merge, final `master` CI and immutable container publication for this candidate.
- Gated external inputs: real Linux/Docker host, SSH values, domain/DNS/TLS, complete production environment/secrets, real monitored contact email, optional SMTP, reviewed official exchange/company files and source compliance approvals.
- Gated validation: fixed 200-event human benchmark, 50k performance run, two-week availability trial, timed recovery drill, accessibility review and product/technical/data-AI/compliance sign-off.
- No production credentials, benchmark labels, contact identities or public endpoint results were fabricated.
