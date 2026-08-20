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

## First Deployment

~~~bash
cp .env.production.example .env.production
docker run --rm caddy:2.10.2-alpine caddy hash-password --plaintext 'replace-this-password'
# Set NEWS_CLAWS_IMAGE_TAG to: git rev-parse --verify HEAD
# Put the hash in BASIC_AUTH_HASH inside single quotes: BASIC_AUTH_HASH='$2a$...'
# Single quotes prevent Compose from expanding the hash's dollar signs.
# Replace every remaining placeholder.
python scripts/validate_production_env.py .env.production
docker compose --env-file .env.production -f compose.prod.yaml config
docker compose --env-file .env.production -f compose.prod.yaml build --pull
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
curl --fail --silent --show-error https://YOUR_DOMAIN/health/live
~~~

Caddy obtains and renews TLS certificates automatically. The public liveness endpoint exposes
only service status. Every UI and API route requires Caddy basic authentication; API mutations
also require the application administrator token.

After DNS and TLS are active, keep the plaintext Basic Auth password out of `.env.production` and export it only for the read-only public smoke:

~~~bash
export BASIC_AUTH_PASSWORD='the-plaintext-password-used-to-create-the-hash'
set -a
. ./.env.production
set +a
python scripts/smoke_public.py "https://$DOMAIN"
unset BASIC_AUTH_PASSWORD ADMIN_TOKEN SMTP_PASSWORD
~~~

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

Record the current `NEWS_CLAWS_IMAGE_TAG` and take an off-host backup. Check out the exact revision to deploy, set `NEWS_CLAWS_IMAGE_TAG` to that full or abbreviated Git SHA in `.env.production`, then run:

~~~bash
python scripts/validate_production_env.py .env.production
docker compose --env-file .env.production -f compose.prod.yaml build --pull
docker compose --env-file .env.production -f compose.prod.yaml up -d
docker compose --env-file .env.production -f compose.prod.yaml ps
curl --fail --silent --show-error https://YOUR_DOMAIN/health/live
~~~

The application runs Alembic migrations before becoming ready. The image tag makes the built release addressable for rollback; do not use `latest` or reuse a previous SHA tag.

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
