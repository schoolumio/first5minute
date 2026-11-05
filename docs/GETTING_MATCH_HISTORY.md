# Getting enough match history for the scanner

## Why the scanner is empty or "Excluded" with real data
The model predicts a game from each team's **earlier** games, using only the last **730 days** of history, and only games whose goal timeline is
reliable. A team needs at least **5 such games to reach Watchlist and 10 to reach Qualified**. With no history, every upcoming game is
"Excluded". The scanner shows only games that have not kicked off yet, so you need two things together: **history** (finished matches with
goal timelines) and **upcoming fixtures** (today onward).

## Why the free plan stalled on day one
API-Football's free plan allows 100 requests a day, serves older seasons rather than the current one, and refuses the bulk timeline request, so
the app falls back to one request per match: about 380 requests per league-season, roughly four days of quota each. Seasons it can read are
also mostly older than the 730-day window, so they would not help today's games anyway. In short: **the free plan cannot build a live scanner**.
Also, progress on your PC's local database does not carry over to the hosted one: they are separate.

## The plan (a paid plan for one month is enough to build the history)
On a paid plan, a league-season downloads in about 20 requests (timelines come 20 at a time), so several leagues and seasons take minutes and a
tiny fraction of the daily quota (Pro is listed at 7,500 requests a day; verify on api-football.com/pricing).

1. **Buy a plan** (Pro is the cheapest paid tier I found, about $19 a month; verify). Keep the key to yourself: it goes only into the host's
   Environment form, never into chat or a file you share.
2. **Set these in Render** (`f5m-api`, and the worker if you have one) under Environment:
   `FOOTBALL_PROVIDER=api_football`, `API_FOOTBALL_KEY` (your key), `FOOTBALL_LEAGUE_IDS` (see step 3),
   `API_FOOTBALL_REQUESTS_PER_MINUTE` (the default is 10; raise it, but keep it below your plan's per-minute limit shown in the
   provider dashboard), `ODDS_PROVIDER=none`. Save; the service redeploys.
3. **Open a Shell** (Render: `f5m-api` > Shell tab; paid web services have one) and run, one at a time:
   ```
   python -m app.cli leagues --search premier
   ```
   Note the id of each league you want (39 is England's Premier League). Add them, comma separated, to `FOOTBALL_LEAGUE_IDS`
   (Render form), then continue. Start with 3 to 5 leagues rather than everything: quality matters more than count, and leagues whose
   timelines do not match final scores are excluded automatically.
4. **Probe before spending quota** (2 requests):
   ```
   python -m app.cli provider-check --league 39 --season 2025
   ```
   You want `"verdict": "OK"` and `timeline_reconciles_with_score: true`. (Season is the year it starts: 2025 means 2025/26. Leagues that
   run within one calendar year use that year.)
5. **Remove the demo data** (it would otherwise mix with real games):
   ```
   python -m app.cli reset-demo
   ```
6. **Download history, resumable** (if a limit is hit, run the same command again later). The window that matters is the last 730 days, so
   pick the last two or three seasons:
   ```
   python -m app.cli backfill-season --league 39 --season 2024 2025 2026
   ```
   Repeat per league (a loop of 20 requests per league-season).
7. **Load fixtures, predict and settle:**
   ```
   python -m app.cli sync
   python -m app.cli scan
   python -m app.cli settle
   ```
   (From then on the worker repeats these automatically. Without a worker you can also run `sync`, `scan` and `settle` from
   Administration > Providers & sync; the season backfill is Shell-only.)
8. **Check quality:** Administration > Competitions (coverage and eligibility per league), then
   ```
   python -m app.cli backtest --days 120
   python -m app.cli doctor
   ```
   `doctor` must show no FAIL. Look at the scanner: games should now be Qualified, Watchlist or Below threshold instead of Excluded. If
   many leagues stay excluded, their goal timelines do not reconcile; choose other leagues.
9. After the history is in, you can drop to a cheaper tier if your daily needs are small: the live job only syncs recent days. Confirm the
   plan still allows the current season before you downgrade.

## If you have no Shell (still on free Render): run it from your PC against the hosted database
Render's database is private by default (`render.yaml` sets no outside access). In Render open `f5m-db` and either add your PC's
public IP to its allowed list or temporarily allow outside access, then copy its **External Database URL**. In Windows Command Prompt:

```bat
call "C:\Users\User\Downloads\first5minute-claude-busy-edison-qgb9ta (3)\first5minute-claude-busy-edison-qgb9ta\backend\.venv\Scripts\activate"
cd /d "NEWFOLDER\backend"
set DATABASE_URL=PASTE-THE-EXTERNAL-DATABASE-URL-HERE
set REDIS_URL=redis://localhost:6379/0
set FOOTBALL_PROVIDER=api_football
set API_FOOTBALL_KEY=PASTE-YOUR-KEY-HERE
set FOOTBALL_LEAGUE_IDS=39
set API_FOOTBALL_REQUESTS_PER_MINUTE=10
python -m app.cli provider-check --league 39 --season 2025
python -m app.cli reset-demo
python -m app.cli backfill-season --league 39 --season 2024 2025 2026
python -m app.cli sync
python -m app.cli scan
python -m app.cli settle
```

Those `set` values exist only in that window and vanish when you close it. Close outside access to the database afterwards. Never share the
URL or the key.

## What "enough" looks like
* At least 5 to 10 reliable finished matches per team within the last 730 days (a full recent season of a top league gives each team about 38).
* Competitions marked eligible in Administration > Competitions.
* A running scan every 30 minutes (needs the worker), so new fixtures get predictions before kick-off.
* Honest expectations: real five-minute no-goal probabilities are around 85-90 %, so few games reach the default 90 % Qualified line. Tune the
  line in Administration > Settings using the backtest, not to make the scanner look busy.
