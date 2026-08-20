# News Claws

News Claws is an evidence-first news intelligence MVP. It collects allow-listed RSS/Atom sources, preserves article versions, groups coverage into events, separates repost count from independent source chains, and produces traceable verification and industry/company impact reports.

The repository implements the local `analysis-api` boundary from `NC-PRD-001` and `NC-TDD-001`. TrendRadar and RSSHub remain separately deployable upstream services. The default local run is vendor-independent and uses deterministic, conservative analysis so no LLM or search key is required.

The current catalog contains 56 source definitions covering China, Hong Kong, Japan, the UK, the US, the EU and global institutions. Collection supports RSS/Atom, JSON APIs, sitemaps, article HTML and authenticated manual-URL submission. Company matching supports SEC and official exchange catalogs. Email subscriptions can target companies or industries with a relevance threshold and immediate or daily delivery.

## Local Setup (Windows PowerShell)

Python 3.12 or 3.13 is required.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
$env:ADMIN_TOKEN = 'dev-admin-token'
.\scripts\dev.ps1
```

Open `http://127.0.0.1:8000`. The local development token defaults to `dev-admin-token`; production refuses to start without an explicit token. Store the token through the `管理令牌` control before using protected actions.

## Local Setup (Linux/macOS)

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
ADMIN_TOKEN=dev-admin-token .venv/bin/python -m uvicorn news_claws.main:app \
  --app-dir apps/analysis_api --host 127.0.0.1 --port 8000
```

## Main Commands

```powershell
# Run all checks
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest -W error --cov=news_claws.domain --cov-branch --cov-fail-under=85
.\.venv\Scripts\python.exe -m pip_audit

# Create a consistent online backup
.\.venv\Scripts\python.exe scripts\backup.py

# Test one source without ingesting it
$env:PYTHONPATH = 'apps/analysis_api'
.\.venv\Scripts\python.exe scripts\source_check.py us_sec_press

# Enforce the live-source release gate
.\.venv\Scripts\python.exe scripts\source_check.py --all --minimum-success-rate 0.95

# Evaluate a real human-labeled benchmark; demo events are rejected
.\.venv\Scripts\python.exe scripts\evaluate_quality.py data\quality-labels.jsonl

# Synchronize the SEC catalog (requires a real contact email)
$env:OUTBOUND_USER_AGENT = 'NewsClaws/0.1 (contact: ops@your-real-domain.tld)'
.\.venv\Scripts\python.exe scripts\sync_sec_companies.py

# Import a reviewed official exchange CSV; use the real export column names
.\.venv\Scripts\python.exe scripts\sync_exchange_companies.py .\official-hkex.csv `
  --market HKEX --country HK --ticker-column StockCode --name-column CompanyName
```

## API

- `GET /health/live`, `GET /health/ready`
- `GET/POST /api/v1/sources`, `PATCH /api/v1/sources/{id}`, `POST /api/v1/sources/{id}/test`
- `POST /api/v1/ingestion/pull`, `POST /api/v1/ingestion/url`
- `GET /api/v1/events`, `GET /api/v1/events/{id}`
- `POST /api/v1/events/{id}/reanalyze`, `POST /api/v1/events/merge`, `POST /api/v1/events/{id}/split`
- `GET /api/v1/reports/{id}?format=json|markdown|html`
- `GET/POST/PATCH/DELETE /api/v1/subscriptions`
- `GET /api/v1/catalog/companies`, `GET /api/v1/notifications`, `POST /api/v1/notifications/dispatch`
- `POST /api/v1/feedback`, `GET /api/v1/jobs`, `GET /api/v1/audit-logs`

Protected endpoints accept `Authorization: Bearer <ADMIN_TOKEN>` or `X-Admin-Token`. API errors use `application/problem+json`.

## Production Deployment

The production profile uses Caddy for automatic HTTPS and whole-site basic authentication. The
application remains a single replica because SQLite is the MVP persistence boundary.

~~~bash
cp .env.production.example .env.production
# Replace every placeholder, generate the Caddy bcrypt hash, and point DOMAIN DNS at the host.
python scripts/validate_production_env.py .env.production
docker compose --env-file .env.production -f compose.prod.yaml config
docker compose --env-file .env.production -f compose.prod.yaml build --pull
docker compose --env-file .env.production -f compose.prod.yaml up -d
~~~

Production defaults disable demo data, require a 32-character administrator secret, validate the
Host header, enforce a 1 MB request limit and run scheduled collection every 15 minutes. See
docs/PRODUCTION_RUNBOOK.md for backup, upgrade, rollback and release gates.

SMTP delivery is disabled unless `NOTIFICATION_ENABLED=true`. When enabled, production validation requires `SMTP_HOST`, a valid `SMTP_FROM`, and `SMTP_PASSWORD` whenever `SMTP_USERNAME` is set. Never put secrets in the repository.

## Data And Compliance

The seeded events are synthetic and visibly marked `DEMO`. Live collection is explicitly user-triggered in the local MVP. Source policies are stored in `config/sources.yaml`; the fetcher accepts only public HTTP(S) destinations, revalidates redirects, limits feed size, and does not bypass authentication, CAPTCHA, paywalls or access restrictions.

The release-quality command requires at least 200 human-labeled, database-backed, non-demo events. Missing events and demo events fail closed. The current repository does not include a real label set, so this gate cannot pass until the owner supplies and reviews one.

Reports distinguish relevance, impact strength and confidence. A primary source confirms only the directly observable publication/action represented by the claim. Multiple reposts of one release share an independence group and do not become multi-source corroboration.

See `docs/OPEN_SOURCE_BOUNDARIES.md`, `docs/LOOP_GOVERNANCE.md` and `docs/adr/` before production or distribution.
