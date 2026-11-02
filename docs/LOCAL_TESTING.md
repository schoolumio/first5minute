# Testing Project Five locally - step by step

Everything in steps 1-8 was executed from a clean clone (fresh virtualenv, empty database, `npm ci`) before this
guide was written. You will run on **synthetic DEMO data** - no API keys, payments or email are needed.

**You need two terminals** (A = backend, B = frontend). Windows users: use section 0 (native) or WSL2 (Ubuntu, Linux commands).

## 0. Windows (native Command Prompt) - use this instead of steps 1-6 below

> Steps 1-8 were executed on Linux. This Windows section uses standard commands but has **not** been run on a Windows machine;
> if something differs, report the exact error. Skip Redis, Celery and `sudo`/`apt` commands entirely (not needed, not for Windows).
> In `cmd`, use **double quotes** (single quotes are not understood) and `copy` instead of `cp`.

**Install (once)** - PostgreSQL 16 from https://www.postgresql.org/download/windows/ (remember the `postgres` password you choose; keep port 5432),
Python 3.13 from https://www.python.org/downloads/ (tick "Add python.exe to PATH") and Node.js 22+ from https://nodejs.org/. Open a **new** terminal, then:

```bat
python --version
node --version
set PATH=%PATH%;C:\Program Files\PostgreSQL\16\bin
psql --version
```

**Databases** (enter your `postgres` password when asked):

```bat
psql -U postgres -c "CREATE USER five WITH PASSWORD 'five' CREATEDB;"
psql -U postgres -c "CREATE DATABASE projectfive OWNER five;"
psql -U postgres -c "CREATE DATABASE projectfive_test OWNER five;"
```

**Config** (from the project folder, e.g. the unzipped `first5minute` folder):

```bat
copy .env.example .env
```

**Backend - Command Prompt A:**

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
alembic upgrade head
python -m app.cli create-admin --email admin@projectfive.local --password "AdminPass123"
python -m app.cli seed-demo
uvicorn app.main:app --reload --port 8000
```

**Frontend - Command Prompt B:**

```bat
cd frontend
npm ci
npm run dev
```

Then open http://localhost:3000 and continue with **step 7 (walkthrough)**. Tests: `pytest` and `ruff check .` in Command Prompt A (venv active),
`npm test`, `npm run typecheck` in B. If PowerShell is your shell, `.venv\Scripts\Activate.ps1` activates the venv (you may first need
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`).

---

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Git | any | |
| Python | 3.12+ (tested 3.13) | needs `venv` |
| Node.js | 22+ | npm included |
| PostgreSQL | 14+ (tested 16) | **required** |
| Redis | 7 | optional (rate limits fall back to memory; Celery workers need it) |

macOS (Homebrew):

```bash
brew install git python@3.13 node@22 postgresql@16 redis libomp
brew services start postgresql@16
```

Ubuntu / WSL2:

```bash
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip postgresql redis-server libgomp1 curl
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs
sudo service postgresql start
```

Check: `python3 --version` (3.12+), `node --version` (22+), `psql --version`.

## 2. Get the code

```bash
git clone https://github.com/schoolumio/first5minute.git
cd first5minute
git checkout claude/busy-edison-qgb9ta
```

## 3. Create the databases

macOS:

```bash
psql postgres -c "CREATE USER five WITH PASSWORD 'five' CREATEDB;"
createdb -O five projectfive
createdb -O five projectfive_test
```

Ubuntu / WSL2:

```bash
sudo -u postgres psql -c "CREATE USER five WITH PASSWORD 'five' CREATEDB;"
sudo -u postgres createdb -O five projectfive
sudo -u postgres createdb -O five projectfive_test
```

Check (should print `1`):

```bash
psql postgresql://five:five@localhost:5432/projectfive -tc "select 1"
```

## 4. Configuration

```bash
cp .env.example .env
```

No edits needed for local testing (demo provider, console email, dev secret). The backend reads the repo-root `.env`
(a `backend/.env`, if you create one, overrides it).

## 5. Backend (Terminal A)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

```bash
alembic upgrade head
python -m app.cli create-admin --email admin@projectfive.local --password 'AdminPass123'
python -m app.cli seed-demo
```

`seed-demo` (~20 s) loads fictional teams, replays the scanner over past days and settles results. Then start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

**Check:** `curl localhost:8000/healthz` returns `{"status":"ok"}` and http://localhost:8000/api/docs shows the API docs.
**Keep Terminal A visible** - in development, emails (verification links, alerts) are printed here.

## 6. Frontend (Terminal B)

```bash
cd frontend
npm ci
npm run dev
```

Open **http://localhost:3000**. A purple "Demo environment" banner confirms you are on synthetic data.

## 7. Guided walkthrough

Expected numbers come from a fresh seed; yours may differ by a few.

1. **Landing page** - hero, how it works, the two markets, pricing, FAQ. Resize to phone width.
2. **Admin sign-in** - `admin@projectfive.local` / `AdminPass123`. Dashboard: stat tiles, top matches per market,
   model performance (DEMO badge), sync status, **performance-over-time chart** (use "View as table").
3. **Scanner + match page** - open *Match scanner*, try filters and sorting. Click a match: probabilities for both markets,
   last 5/10/20 form, home/away split, first-goal timing chart, head-to-head, competition baseline.
   Odds panel says "No odds available" - correct, no odds provider is configured.
4. **Register a normal user** - sign out, *Create account*. The verification link is printed in **Terminal A**
   (`.../verify-email?token=...`). Open it, then sign in.
   - Free plan: scanner shows **3 matches** and an upgrade note; Pro filters show "Pro filter" locks.
5. **Upgrade through admin** - as admin: *Admin -> Users*, search the user, set Plan = `pro`. Reload the user's scanner: about
   **21 matches**, advanced filters unlocked, odds panel available on match pages.
6. **Eligibility (Phase 4)** - *Admin -> Competitions*: **Demo Regional Cup** is `ineligible` (~67% timeline coverage).
   In the user's scanner tick **Excluded**: its fixtures appear with "Competition not eligible: ...". Set the cup's mode to
   *force on*, then *Admin -> Providers & sync -> scan*: they are re-predicted. Set it back to *auto*.
7. **Notifications** - as the Pro user: *Account -> Profile*, enable *Newly qualified matches* and *Also send by email*; save a match
   (bookmark icon) and enable *Saved match settled*. As admin: *Settings*, set Market A qualified to `85` and watchlist to `80`,
   save, then *Providers & sync -> scan*. The bell shows new "Qualified" notifications and the **email digest is printed in Terminal A**.
8. **Models (Phase 3)** - *Admin -> Models -> Train & evaluate candidates*. Click *Compare* on a version: candidates, confidence
   intervals vs the baseline, and why promotion is blocked (demo data, small sample). *Activate* (accept the warning), run *scan*,
   open a match - it says which model produced the estimate - then *Roll back to baseline*.
9. **Responsible gambling** - *Account -> Responsible gambling*: set a 24-hour limit, then *Bet tracking*, record a bet above it
   (warning appears). Self-exclude for 1 day: bet tracking and sportsbook links are blocked.
10. **Prediction history** - filters by market/outcome/category; calibration chart and walk-forward table (Pro).
11. **Audit trail** - *Admin -> Audit log* lists every change you made.

## 8. Automated tests

```bash
cd backend && source .venv/bin/activate
pytest                 # 110 tests, ~70 s, uses the projectfive_test database
ruff check .
```

```bash
cd frontend
npm test && npm run typecheck && npm run build
```

## 9. Optional: background workers

```bash
redis-cli ping         # PONG
cd backend && source .venv/bin/activate
celery -A app.workers.celery_app worker -l info -Q default,ingestion
```

```bash
cd backend && source .venv/bin/activate
celery -A app.workers.celery_app beat -l info
```

Beat runs sync every 30 min, scan at :05/:35, settlement every 15 min, training weekly.

## 10. Optional: real football data

1. Put a key in `.env`: `FOOTBALL_PROVIDER=api_football` + `API_FOOTBALL_KEY=...` (or `sportmonks` + `SPORTMONKS_TOKEN=...`); restart the API.
2. Remove demo data: `python -m app.cli reset-demo`.
3. Pull history and upcoming fixtures: `python -m app.cli backfill --days 90`, then `python -m app.cli sync`, `scan`, `settle`.
4. Check *Admin -> Providers & sync* (health, errors) and *Competitions* (timeline coverage - poor leagues get excluded automatically).

Adapters were built from provider documentation and tested only with mock responses - **verify against your plan's real payloads**
(especially goal-minute precision and which leagues include events).

## 11. Optional: Paystack test payments

`.env`: `PAYMENT_PROVIDER=paystack`, `PAYSTACK_SECRET_KEY=sk_test_...`. Expose the API (`ngrok http 8000`) and register
`https://<tunnel>/api/v1/webhooks/paystack` in the Paystack dashboard. Pay with Paystack's documented **test** cards.

## 12. Optional: Docker Compose (not verified in the build sandbox)

```bash
cp .env.example .env
docker compose up --build
docker compose exec api python -m app.cli create-admin --email admin@projectfive.local --password 'AdminPass123'
docker compose exec api python -m app.cli seed-demo
```

## 13. Reset / clean up

```bash
python -m app.cli seed-demo --reset     # refresh demo data (dates anchor to the day you seed - re-run daily)
python -m app.cli reset-demo            # remove demo data only
```

Full wipe: `dropdb projectfive && createdb -O five projectfive`, then `alembic upgrade head` again.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `connection refused` on port 5432 | start PostgreSQL (`brew services start postgresql@16` / `sudo service postgresql start`) |
| `password authentication failed for user "five"` | re-run the `CREATE USER` command in step 3 |
| `database "projectfive_test" does not exist` | `createdb -O five projectfive_test` |
| Page says "Network error - is the API running?" | start Terminal A; if the API uses another port run `BACKEND_URL=http://localhost:8001 npm run dev` |
| Sign-in fails after wiping the database | run `create-admin` again |
| No verification email | in dev it is printed in Terminal A, not sent |
| Redis warning in the API log | harmless: rate limiting falls back to memory |
| `libgomp` / `libomp` error importing lightgbm | `sudo apt install libgomp1` / `brew install libomp` |
| Scanner empty / old dates | demo data is anchored to the seed day: `python -m app.cli seed-demo --reset` |
| `Unsafe production configuration` | you set `ENVIRONMENT=production`; use `development` locally |
