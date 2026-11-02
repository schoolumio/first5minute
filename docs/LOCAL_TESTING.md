# Testing First5Minute locally - step by step

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
python -m app.cli create-admin --email admin@first5minute.local --password "AdminPass123"
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

For the odds walkthrough (step 7.12) open `.env` and change `ODDS_PROVIDER=none` to `ODDS_PROVIDER=demo` **before** `seed-demo`
(already seeded? change it, restart the API, then run `python -m app.cli odds`). Everything else needs no edits (demo football data, console email, dev secret). The backend reads the repo-root `.env`
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
python -m app.cli create-admin --email admin@first5minute.local --password 'AdminPass123'
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
2. **Admin sign-in** - `admin@first5minute.local` / `AdminPass123`. Dashboard: stat tiles, top matches per market,
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
12. **Odds & sportsbook links (Phase 5)** - needs `ODDS_PROVIDER=demo` (step 4). The demo odds are synthetic, derived from the model plus a margin,
    so they never contain value - they exist only to exercise the screens. As admin or a Pro user:
    - *Odds comparison* (sidebar): best fresh price per prediction, model fair odds and estimated edge; try the edge filter and sorting.
    - Open a match: the **Odds comparison** card shows three DEMO sportsbooks. "Demo Sportsbook C" carries a warning icon: it settles on a
      different (05:00) rule than the model, so its odds are not directly comparable. The chart plots best price against the model's fair odds.
    - Click **Open**: a responsible-gambling dialog appears; **Continue** opens `example.com/demo-sportsbook/...` in a new tab, then offers
      **Record this bet** (prefilled odds/market/sportsbook). Set a 24-hour limit and record a bet above it, then try Open again: you must
      explicitly acknowledge the limit. Self-exclude: links are disabled.
    - *Admin -> Bookmakers*: paste `{"rows":[{"fixture_id":<id from the match URL>,"bookmaker_code":"acme-book","bookmaker_name":"Acme Book","market":"MARKET_A","decimal_odds":1.09,"event_ref":"a1"}]}`
      into **Import odds**. "Acme Book" appears under **Pending review** (inactive, hidden from users). Give it an `https://...{event_ref}...` link template, countries
      (e.g. `NG`) and approve it. A user whose profile country is not NG will not see it; one whose country is NG will.
    - *Admin -> Bookmakers -> Fetch odds now* re-polls the provider; unchanged prices are not re-stored, withdrawn ones are marked suspended.

## 8. Automated tests

```bash
cd backend && source .venv/bin/activate
pytest                 # 162 tests, ~90 s, uses the projectfive_test database
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

## 10. Real football data (API-Football)

Plan limits matter: API-Football's **free plan allows 100 requests/day and 10/minute**. This app fetches match timelines in bulk (20 per
request) and only for the leagues you list, so a few leagues fit; a large backfill may take several days on the free plan (it **resumes
where it stopped**). Paid plans have far higher limits. The adapter was written from the provider documentation and has only been tested
against mock responses - the `provider-check` step below tells you whether real payloads parse correctly **before** you spend quota.

**Which plan do you have?** API-Football's **free plan** allows 100 requests/day and usually only *older seasons* (not the current one);
paid plans allow the current season and far more requests. You do not have to guess - the commands below tell you.

**Windows (cmd), in Command Prompt A with the venv active (`.venv\Scripts\activate`) inside `backend`:**

1. Get a key at https://dashboard.api-football.com and put it in `.env` (copy `.env.example` to `.env` first, then `notepad ..\.env`):
   ```
   FOOTBALL_PROVIDER=api_football
   API_FOOTBALL_KEY=your-key-here
   API_FOOTBALL_REQUESTS_PER_MINUTE=10
   FOOTBALL_LEAGUE_IDS=39
   ODDS_PROVIDER=none
   ```
2. Find league ids (1 request): `python -m app.cli leagues --search premier`  (39 = England Premier League).
3. Remove the demo data: `python -m app.cli reset-demo`
4. **Probe one league-season (2 requests)** - shows whether your plan allows it and whether the goal timelines are usable:
   ```bat
   python -m app.cli provider-check --league 39 --season 2023
   ```
   Look for `"verdict": "OK: ..."`, `timeline_reconciles_with_score: true`, and `estimated_requests_to_download`.
   *(Season = the year it starts: 2023 means 2023/24.)* If the message mentions your plan, try an older year (2022, 2021).
5. **Download whole seasons (resumable - if the daily limit is hit, run the same command again later).** Paid plans download a
   season in about 20 requests (timelines are fetched 20 at a time). **Free plans refuse that bulk request**, so the app automatically
   switches to one request per match (about 380 per season = roughly 4 days at 100 requests/day). It downloads matches oldest-first, saves
   after every match and tells you how many daily runs remain; run the same command once a day until it reports `timelines_missing: 0`:
   ```bat
   python -m app.cli backfill-season --league 39 --season 2022 2023
   ```
6. **Real accuracy numbers.** Walk-forward evaluation of the baseline on the downloaded matches (predicts each match using only
   earlier matches), then the advanced-model comparison:
   ```bat
   python -m app.cli backtest --from 2023-09-01 --to 2024-05-31
   python -m app.cli train
   ```
7. **Current season (paid plans only):** `python -m app.cli backfill-season --league 39 --season 2026`, then `python -m app.cli sync`,
   `scan`, `settle`. The scanner only shows matches that have **not kicked off yet**, so with historical seasons only, the scanner is
   empty by design - review results in *Admin -> Models*, *Admin -> Competitions* and the `backtest` output.
8. Start the API (`uvicorn app.main:app --reload --port 8000`) and the website as before.

What to expect: teams need at least 5 (watchlist) to 10 (qualified) matches with reliable event timelines, so a 120-day backfill of a
top league is the minimum. Real five-minute no-goal probabilities are about 85-90 %, so few matches reach the default 90 % qualified
threshold - tune it in *Admin -> Settings*. Leagues whose timelines do not reconcile with scores are excluded automatically.
Do not enable `ODDS_PROVIDER=api_football` until you have confirmed your bookmakers actually price these markets.

**Linux / macOS:** same commands, with `source .venv/bin/activate` and `nano ../.env`.

## 11. Optional: Paystack test payments

`.env`: `PAYMENT_PROVIDER=paystack`, `PAYSTACK_SECRET_KEY=sk_test_...`. Expose the API (`ngrok http 8000`) and register
`https://<tunnel>/api/v1/webhooks/paystack` in the Paystack dashboard. Pay with Paystack's documented **test** cards.

## 12. Optional: Docker Compose (not verified in the build sandbox)

```bash
cp .env.example .env
docker compose up --build
docker compose exec api python -m app.cli create-admin --email admin@first5minute.local --password 'AdminPass123'
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
