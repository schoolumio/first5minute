# First5Minute

**The first five minutes. Decoded.** Global football intelligence for two five-minute markets:

| Market | Wins when | Model |
|---|---|---|
| **A** - No goal in the first five minutes | score is 0-0 at the settlement cutoff | `P = e^-(λh + λa)` |
| **B** - Level at five minutes | scores are equal at the cutoff (0-0, 1-1, 2-2 ...) | `P = Σk P(H=k)·P(A=k)` (Bessel closed form) |

First5Minute is an analytics platform, **not a guaranteed betting system**. Model outputs are labelled
*uncalibrated* until sufficient out-of-sample evidence exists. 18+ only.

> **Data honesty.** Without provider credentials the app runs on a clearly labelled **DEMO** provider
> (fictional teams such as "Ashford Rovers" in "Demo Premier Division"). Every demo row carries
> `is_demo = true`, and the UI shows a permanent demo banner. Odds are never invented: with no odds
> provider configured the app says "No odds available".

---

## Stack

- **Backend** - Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis, Celery, NumPy/SciPy, structlog, Sentry (optional)
- **Frontend** - Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn-style components, Recharts, Lucide
- **Payments** - Paystack (NGN + international cards), HMAC-SHA512 webhook verification
- **Infra** - Docker, Docker Compose, GitHub Actions CI

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design, phase status and remaining dependencies.

## Repository layout

```
backend/
  app/
    api/v1/          REST routers (auth, account, fixtures, scanner, predictions, odds, subscriptions, admin, system)
    core/            config, database, security, logging, rate limiting
    models/          SQLAlchemy models (29 tables)
    providers/       football (API-Football, Sportmonks, demo), odds, payments adapters + resilient HTTP client
    ingestion/       normalised-data persistence, dedup, raw payloads, sync jobs
    engine/          settlement (5' cutoff), features (leak-free), Poisson models, metrics, walk-forward backtest
    scanner/         scan, categorise, persist immutable predictions, settle, notify
    services/        auth, entitlements, billing, audit, email, settings
    workers/         Celery app + beat schedule, shared jobs
    cli.py           create-admin, seed-demo, sync, scan, settle, backtest
  alembic/           migrations (schema + prediction immutability trigger + reference data)
  tests/             pytest suite against PostgreSQL (mock provider responses)
frontend/
  src/app/           (marketing) landing & pricing · (auth) login/register/verify/reset · (app) dashboard, scanner, matches, predictions, account, admin
  src/components/    design system (ui/), charts, layout, brand
  src/lib/           API client (CSRF + refresh), auth context, hooks, formatting
docker-compose.yml   db, redis, api, worker, beat, web
```

> **New here? Follow the verified step-by-step walkthrough: [`docs/LOCAL_TESTING.md`](docs/LOCAL_TESTING.md).**

## Quick start (local, without Docker)

Prerequisites: Python 3.12+, Node 22+, PostgreSQL 16, Redis 7.

```bash
cp .env.example .env
```

```bash
createuser -P five && createdb -O five projectfive   # password: five (or update DATABASE_URL)
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head                                   # create schema + reference data
python -m app.cli create-admin --email you@example.com # prompts for a password
python -m app.cli seed-demo                            # DEMO data + replayed predictions + backtest
python -m app.cli train                                # Phase 3: train & walk-forward evaluate ML models
uvicorn app.main:app --reload --port 8000              # API docs: http://localhost:8000/api/docs
```

### Background workers

```bash
cd backend
celery -A app.workers.celery_app worker -l info -Q default,ingestion
```

```bash
cd backend
celery -A app.workers.celery_app beat -l info
```

Schedule: fixture sync every 30 min · scanner at :05/:35 · settlement every 15 min · auto-renewal/reminders/expiry every 15 min · queued emails every 5 min · walk-forward backtest nightly.
Weekly (Sunday 04:23 UTC) the **train** job evaluates the advanced models and promotes one only if every statistical gate passes.
Every job can also be run on demand from **Admin → Providers & sync** or with `python -m app.cli <job>`.

### Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000 (proxies /api/v1 to BACKEND_URL)
```

## Quick start (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

```bash
docker compose exec api python -m app.cli create-admin --email you@example.com
docker compose exec api python -m app.cli seed-demo
```

## Environment variables

All variables are documented in [`.env.example`](.env.example). The important ones:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | JWT signing key - **must** be random and ≥32 chars in production (startup refuses otherwise) |
| `DATABASE_URL`, `REDIS_URL` | PostgreSQL and Redis connections |
| `FOOTBALL_PROVIDER` | `demo`, `api_football` or `sportmonks` |
| `API_FOOTBALL_KEY` / `SPORTMONKS_TOKEN` | provider credentials (server-side only) |
| `ODDS_PROVIDER` | `none`, `api_football` or `demo` (synthetic, labelled - local testing only) |
| `PAYMENT_PROVIDER`, `PAYSTACK_SECRET_KEY` | `paystack` enables checkout, webhooks and auto-renewal; `demo` is a local simulator (never in production) |
| `EMAIL_BACKEND` | `console` (dev - links appear in the API log) or `smtp` |
| `COOKIE_SECURE` | `true` behind HTTPS (required in production) |

## Connecting real data

> Step-by-step (Windows cmd and Linux/macOS): **docs/LOCAL_TESTING.md, section 10**. A league allowlist (`FOOTBALL_LEAGUE_IDS`) is required.

1. Obtain an API-Football or Sportmonks key and set `FOOTBALL_PROVIDER` + the key.
2. Run `python -m app.cli sync` (or let Celery beat run) - fixtures for the past 2 and next 3 days are pulled; final fixtures are fetched with full event timelines.
3. Backfill history per competition before relying on predictions: the scanner **excludes** fixtures whose teams lack enough reliable, timestamped matches.
4. Check **Admin → Competitions** for timeline coverage and disable competitions with poor event data.
5. Confirm the provider's minute convention matches your bookmaker's settlement rule (**Admin → Settings → Settlement rules**).
6. Remove demo data with `python -m app.cli reset-demo`.

## Testing

```bash
cd backend && pytest          # needs a PostgreSQL test DB (TEST_DATABASE_URL, default projectfive_test)
```

```bash
cd backend && ruff check .
```

### Machine-learning models (Phase 3)

```bash
cd backend
python -m app.cli train                  # evaluate candidates; register versions; promote only if all gates pass
python -m app.cli train --no-promote     # evaluate and register only
python -m app.cli rollback-model --market MARKET_A
```

Set `MODEL_DIR` (persist it!) and optionally `MLFLOW_TRACKING_URI` (`pip install -r requirements-ml.txt`;
MLflow 3 needs a database backend such as `sqlite:///mlflow.db` or a tracking server). Review candidates in
**Admin > Models**. See `docs/ARCHITECTURE.md` section 3b for the methodology and promotion gates.

```bash
cd frontend && npm test && npm run typecheck && npm run build
```

The backend suite (180 tests) covers authentication, CSRF, refresh-token rotation, five-minute cutoff
rules, Poisson calculations, ingestion/normalisation, provider adapters with mock payloads, retry and
rate limiting, data-leakage guards, prediction immutability, settlement corrections, walk-forward
backtesting, plan permissions, admin permissions and Paystack webhooks.

## Deployment

- Build images with `docker compose build` (or the individual `backend/Dockerfile` and `frontend/Dockerfile`). The API container runs `alembic upgrade head` on start.
- Run API, worker and beat from the same image; scale workers horizontally. Use managed PostgreSQL (e.g. AWS RDS) with automated daily snapshots and point-in-time recovery, and managed Redis (ElastiCache).
- Terminate TLS at a load balancer, set `COOKIE_SECURE=true`, `ENVIRONMENT=production`, `EMAIL_BACKEND=smtp` and a strong `SECRET_KEY`.
- Register the Paystack webhook URL `https://<api-host>/api/v1/webhooks/paystack`.
- Set `SENTRY_DSN` for error monitoring; logs are structured JSON outside development.
- Backups and retention: see `docs/ARCHITECTURE.md` → *Security & operations*.

## Responsible gambling

Users can set 24-hour and 30-day stake limits, reality-check reminders and self-exclusion
(which hides sportsbook links and pauses bet tracking). First5Minute never holds funds, never places
bets and never asks for sportsbook credentials.
