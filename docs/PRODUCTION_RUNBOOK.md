# News Claws Production Runbook

This runbook targets one Linux host with Docker Engine and Compose v2. The MVP uses one
application replica and SQLite WAL. Do not scale the application service horizontally.

## Required Inputs

- A DNS name whose A/AAAA record points to the host.
- Inbound TCP 80 and TCP/UDP 443.
- A unique administrator token of at least 32 random characters.
- A Caddy bcrypt password hash for the whole-site login.
- A reviewed live-source allow-list and compliance owner.
- A real monitored contact email in `OUTBOUND_USER_AGENT`; SEC synchronization must not use a placeholder.
- Official, reviewed company exports for each required A-share or Hong Kong exchange.
- SMTP credentials and a verified sender when email notifications are enabled.
- A human-labeled benchmark containing at least 200 non-demo events.
- A GitHub Container Registry credential limited to `read:packages` while the image is private.

## First Deployment

~~~bash
cp .env.production.example .env.production
docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext 'replace-this-password'
# Set NEWS_CLAWS_IMAGE_TAG to the full SHA shown by the successful container workflow.
# Put the hash in BASIC_AUTH_HASH inside single quotes: BASIC_AUTH_HASH='$2a$...'
# Single quotes prevent Compose from expanding the hash's dollar signs.
# Replace every remaining placeholder.
export CR_PAT='a-token-limited-to-read-packages'
echo "$CR_PAT" | docker login ghcr.io -u SHUREEEE --password-stdin
unset CR_PAT
python scripts/validate_production_env.py .env.production
docker compose --env-file .env.production -f compose.prod.yaml config
docker compose --env-file .env.production -f compose.prod.yaml pull analysis-api
docker compose --env-file .env.production -f compose.prod.yaml up -d --no-build
docker compose --env-file .env.production -f compose.prod.yaml ps
curl --fail --silent --show-error https://YOUR_DOMAIN/health/live
~~~

Caddy obtains and renews TLS certificates automatically. The public liveness endpoint exposes
only service status. Every UI and API route requires Caddy basic authentication; API mutations
also require the application administrator token.

## GitHub Production Environment

The manual `deploy-production` workflow provides the same single-host Compose deployment with
pre-deployment backup, immutable-image verification, readiness wait and public HTTPS smoke. It does
not bypass any release gate. Configure a GitHub environment named `production`, restrict it to the
`master` branch and require an owner review before deployment.

Set these environment variables:

- `PRODUCTION_HOST`: verified DNS hostname or IPv4 address of the SSH host.
- `PRODUCTION_USER`: unprivileged deployment user with Docker access.
- `PRODUCTION_SSH_PORT`: SSH port; defaults to `22`.
- `PRODUCTION_PATH`: specific writable absolute path; defaults to `/srv/news-claws`.
- `GHCR_USER`: registry username; defaults to the repository owner.

Set these environment secrets:

- `PRODUCTION_SSH_PRIVATE_KEY`: dedicated deployment key with no unrelated host access.
- `PRODUCTION_KNOWN_HOSTS`: pinned host-key line verified through an independent channel. Never
  replace it with disabled host-key checking.
- `PRODUCTION_ENV_FILE`: complete production environment based on `.env.production.example`. The
  workflow replaces only `NEWS_CLAWS_IMAGE` and `NEWS_CLAWS_IMAGE_TAG`, then validates everything.
- `GHCR_READ_TOKEN`: token limited to `read:packages`.
- `BASIC_AUTH_PASSWORD`: plaintext corresponding to `BASIC_AUTH_HASH`, used only by public smoke.

Dispatch the workflow from `master` with the full 40-character SHA produced by a successful
`publish-container` run. The SHA must be an ancestor of `master`, and the workflow resolves its
registry digest before opening SSH. The host refuses to start the pulled image unless its digest
matches that verified value. Leave `rollback_approved=false` unless the migration history has been
reviewed as compatible with the previous image. When approved, readiness or public-smoke failure
restores the previous release; otherwise the workflow fails closed for operator review.

The automated backup remains in the encrypted/persistent `analysis-backups` Docker volume. It is
not an off-host disaster-recovery copy, so the off-host backup gate below still applies.

After DNS and TLS are active, keep the plaintext Basic Auth password out of `.env.production` and export it only for the read-only public smoke:

~~~bash
export BASIC_AUTH_PASSWORD='the-plaintext-password-used-to-create-the-hash'
set -a
. ./.env.production
set +a
python scripts/smoke_public.py "https://$DOMAIN"
unset BASIC_AUTH_PASSWORD ADMIN_TOKEN SMTP_PASSWORD
~~~


## Article Extraction, Website Discovery And External LLM

The production image contains Newspaper4k and news-please. Both receive only HTML fetched by the application's SSRF-safe client. Keep a source at `content_policy=metadata_only` when article-page retrieval or excerpt retention is not approved.

Website discovery is disabled by default. For every approved `method=website` source, set `parser=news-please`, use an excerpt-enabled content policy, and add only its exact source ID to the comma-separated `NEWS_PLEASE_DISCOVERY_SOURCE_IDS`. Record the terms/copyright reviewer and rate policy in the source compliance notes. The collector checks `robots.txt`, follows only same-origin HTML links and fails closed on robots retrieval errors other than a missing 404/410 file.

Deterministic analysis remains the no-vendor default. To enable an OpenAI-compatible Chat Completions endpoint, configure:

~~~bash
LLM_PROVIDER=openai-compatible
LLM_MODEL=your-structured-output-model
LLM_API_BASE_URL=https://provider.example/v1
LLM_API_KEY=replace-through-the-secret-store
LLM_TIMEOUT_SECONDS=30
LLM_MAX_OUTPUT_TOKENS=2000
LLM_PER_EVENT_BUDGET=0.50
DAILY_LLM_BUDGET=5.00
LLM_INPUT_COST_PER_MILLION=0
LLM_OUTPUT_COST_PER_MILLION=0
~~~

Set token prices to the provider's current per-million-token billing rates; zero means cost cannot be estimated and is unsuitable for a paid production provider. The validator rejects negative, NaN and infinite values. Strict JSON Schema output, evidence/target allow-lists and one repair call are mandatory. A second schema failure becomes a dead job with no valid report; provider/network errors enter `retry_wait`. Failed calls with valid usage metadata still consume the daily budget.

Before enabling either feature in production, run the source test for each website source and one controlled model analysis covering success, repair success, dead-schema and provider-unavailable paths. Review the resulting source diagnostics, pipeline jobs, analysis runs, token counts and costs.
## Company Catalog

Run catalog synchronization against the same `DATABASE_URL` used by the application. SEC requires a descriptive user agent with a real monitored email:

~~~bash
export OUTBOUND_USER_AGENT='NewsClaws/0.1 (contact: ops@YOUR_DOMAIN)'
python scripts/sync_sec_companies.py
~~~

Download A-share and Hong Kong company lists from the relevant official exchange. Review the file and map its real column names; do not relabel an unofficial list as an exchange export:

~~~bash
python scripts/sync_exchange_companies.py /secure/imports/sse-companies.csv \
  --market SSE --country CN --ticker-column SecurityCode --name-column CompanyName
python scripts/sync_exchange_companies.py /secure/imports/szse-companies.csv \
  --market SZSE --country CN --ticker-column SecurityCode --name-column CompanyName
python scripts/sync_exchange_companies.py /secure/imports/hkex-companies.csv \
  --market HKEX --country HK --ticker-column StockCode --name-column CompanyName
~~~

Use `--alias-column` once per optional alias column. Re-running an import is an idempotent upsert. Record the official download URL, retrieval time, checksum, row count and reviewer in the release evidence.

## Email Notifications

Keep `NOTIFICATION_ENABLED=false` until SMTP is verified. To enable delivery, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_STARTTLS`, and, when required, `SMTP_USERNAME` plus `SMTP_PASSWORD`. Re-run:

~~~bash
python scripts/validate_production_env.py .env.production
docker compose --env-file .env.production -f compose.prod.yaml up -d
~~~

Create a test subscription through `/subscriptions`, generate a qualifying report, dispatch the queue and verify receipt. Confirm that retries are idempotent and that no recipient address appears in logs or idempotency keys.

## Pre-release Data Gates

Run these from the deployment network after migrations and company synchronization:

~~~bash
python scripts/source_check.py --all --minimum-success-rate 0.95
python scripts/evaluate_quality.py /secure/benchmarks/quality-labels.jsonl \
  --minimum-events 200 --cluster-threshold 0.90 \
  --industry-threshold 0.80 --company-threshold 0.80
~~~

The source gate allows at most transient failure within the 95% threshold; investigate repeated failures rather than disabling sources solely to pass the gate. The quality gate rejects unknown database IDs and demo events. Missing, synthetic or unreviewed labels are a release blocker.

## Backup

~~~bash
docker compose --env-file .env.production -f compose.prod.yaml exec analysis-api \
  python scripts/backup.py --database /data/analysis.db --output-dir /backups
docker compose --env-file .env.production -f compose.prod.yaml exec analysis-api \
  find /backups -maxdepth 1 -type f -name 'analysis-*' -print
~~~

Copy both the database and matching SHA-256 file off-host. A backup kept only on the application
host is not a disaster-recovery backup.

## Upgrade

Record the current `NEWS_CLAWS_IMAGE_TAG` and take an off-host backup. Set `NEWS_CLAWS_IMAGE_TAG`
to the full Git SHA published by the successful container workflow, then run:

~~~bash
python scripts/validate_production_env.py .env.production
docker compose --env-file .env.production -f compose.prod.yaml pull analysis-api
docker compose --env-file .env.production -f compose.prod.yaml up -d --no-build
docker compose --env-file .env.production -f compose.prod.yaml ps
curl --fail --silent --show-error https://YOUR_DOMAIN/health/live
~~~

The application runs Alembic migrations before becoming ready. The full-SHA image tag makes the
published release addressable for rollback; use only the full-SHA tag and never reuse one.

## Rollback

If the current schema remains compatible, restore the previous `NEWS_CLAWS_IMAGE_TAG` in `.env.production` and run:

~~~bash
python scripts/validate_production_env.py .env.production
docker compose --env-file .env.production -f compose.prod.yaml up -d --no-build
docker compose --env-file .env.production -f compose.prod.yaml ps
curl --fail --silent --show-error https://YOUR_DOMAIN/health/live
~~~

If a schema downgrade is required, stop the application and restore a verified pre-upgrade backup to a new database file. Never overwrite the only copy of the current database. Validate `PRAGMA integrity_check`, start the previous image, then perform liveness, authentication, event-detail and report smoke tests.

## Release Gates

- CI, dependency audit, migration check and container build are green.
- Every website source is explicitly allow-listed, passes robots-aware source testing and has approved terms/copyright/rate notes.
- When external LLM mode is enabled, a controlled production-provider smoke proves strict output, retry/dead states and billed token-cost accounting without exposing the API key.
- Production environment validation passes and contains no placeholder secrets.
- SEC and each required official exchange company catalog are imported and reviewed.
- At least 95% of enabled live sources pass from the deployment network.
- The 200-event human benchmark passes cluster, industry and company thresholds.
- SMTP delivery and retry behavior pass when notifications are enabled.
- Backup and restore have been exercised on the release candidate.
- Public HTTPS, basic authentication, Host validation and security headers pass.
- Desktop/mobile UI, URL ingestion, subscriptions, notifications, authenticated API and audit-log smoke tests pass against the public URL.
- A rollback to the previous image plus a verified backup has been rehearsed or explicitly approved.
- The owner has approved the real company/entity catalog and source compliance notes.
