# From demo to public launch: what you need, in what order, and what it costs

Purpose: a complete checklist so you can price the launch. Prices below come from web searches done on 2026-11-05 plus my recollection where
marked. **Verify every price on the provider's own page before you budget.** Amounts are in US dollars as the providers quote them; convert at
today's rate yourself.

## 0. Where you are today

| Part | Today | To be real you need |
|---|---|---|
| Website, sign-in, accounts, themes | **Real** | a custom domain, real email (section 6) |
| Scanner games | **Demo data** | a paid football-data plan + recent history (section 2) |
| Odds board / edge | **Empty or demo** | a licensed odds source; most bookmakers do not price five-minute markets (section 3) |
| "Generate booking code" | **Demo bookmakers only** (`DEMO-` codes) | an official integration per bookmaker (section 4): this is the long pole |
| Subscriptions / payments | **Demo/off** | a live Paystack account (section 5) |
| Legal | none | a company, policies, a lawyer's opinion (section 7) |

Order of work (the long-lead items start first, in parallel):
1. **This week:** start bookmaker outreach (section 4) and the legal opinion (section 7). Both take weeks and cost little to start.
2. Upgrade hosting and switch on real games (sections 1-2).
3. Switch on payments and email (sections 5-6).
4. Odds (section 3) once you know which source you can legally use.
5. Launch with the converter honestly marked "not connected" for any bookmaker without an integration, and add bookmakers one by one.

---

## 1. Hosting upgrade (needed before real data: you need the worker and a Shell)

Free Render has no worker (no scheduled sync/scan/settle) and no Shell. Real data needs both.

1. Render: upgrade `f5m-db` (removes the 30-day deletion), `f5m-api` (stops sleeping, adds a Shell tab), and enable the `f5m-worker` block in
   `render.yaml` (see `docs/DEPLOY_CLOUD.md`, Part 6).
2. Vercel: move to a paid plan once the public uses it (the free Hobby plan is for non-commercial use; read its terms).
3. Domain: buy one (for example `first5minute.com`); in Vercel add it under Settings > Domains; then in Render set `FRONTEND_URL` and
   `CORS_ORIGINS` to the new address (also keep `https://first5minute-frontend.vercel.app` working until you switch).
4. Error monitoring: create a Sentry project and set `SENTRY_DSN`. Uptime: a monitor on `/healthz`.
5. Backups: confirm the paid database plan's backup retention and **test a restore once**.

**Cost (monthly, from my search of Render's pricing; verify):** web service Starter about $7 (512 MB); background worker Starter about $7;
Postgres Basic-256MB about $6 plus storage (about $0.30 per GB, small at first); a larger API instance (Standard about $25, 2 GB) if you see
out-of-memory restarts. Redis: the free Key Value is fine to start. Vercel Pro: my recollection is about $20 per user per month; verify.

## 2. Real games in the scanner

> Short on history? The detailed steps (why the free plan stalled, the exact commands, and the Windows version) are in
> [`GETTING_MATCH_HISTORY.md`](GETTING_MATCH_HISTORY.md).

What is needed: a football-data account, an API key, a list of leagues, and **history** (the model needs 5-10 earlier matches with a reliable
goal timeline per team before a game can be anything but "Excluded").

1. **Choose a plan.** The app supports API-Football (and Sportmonks). API-Football's published daily limits: Free 100, Pro 7,500, Ultra 75,000,
   Mega 150,000 requests per day; prices I found: Pro about $19, Ultra about $29, Mega about $39 per month (verify on api-football.com/pricing).
   The free plan cannot read the current season, so **a paid plan is required for a live scanner**. Start with Pro or Ultra, and watch the
   quota in its dashboard.
2. **Put the key in Render, never in chat:** `f5m-api` > Environment (and the worker): `FOOTBALL_PROVIDER=api_football`,
   `API_FOOTBALL_KEY=...` (type it in the form), `API_FOOTBALL_REQUESTS_PER_MINUTE=` (raise it above 10 on a paid plan, within your plan's
   limit), `FOOTBALL_LEAGUE_IDS=39,...`, `FOOTBALL_ALLOW_ALL_LEAGUES=false` (leave it, or the sync pulls every competition and burns the quota).
3. **Find league ids** (Render Shell on the API service): `python -m app.cli leagues --search premier` (repeat per league you want, including
   Nigerian and African leagues if that is your audience; coverage of goal timelines varies by league: the app excludes leagues whose
   timelines do not reconcile with final scores).
4. **Probe before spending quota:** `python -m app.cli provider-check --league 39 --season 2025` (2 requests). Look for `"verdict": "OK"`.
5. **Remove the demo data:** `python -m app.cli reset-demo`. Then set `BOOKING_CONVERTER_DEMO=false` later only when you are ready (section 4).
6. **Download history (resumable):** `python -m app.cli backfill-season --league 39 --season 2024 2025`. On a paid plan a season is about 20
   requests per league. Add the current season too.
7. **Run the pipeline once:** `python -m app.cli sync`, then `scan`, then `settle`. After that the worker repeats them on schedule
   (sync every 30 minutes, scan twice an hour, settle every 15 minutes).
8. **Check quality:** Administration > Competitions (eligibility and coverage per league), `python -m app.cli backtest --days 120`, and tune
   the thresholds in Administration > Settings. Real five-minute no-goal probabilities are around 85-90 %, so few games reach the default 90 %
   "Qualified" line: set the line from evidence, not to make the scanner look busy.
9. **Readiness:** `python -m app.cli doctor` must show no FAIL.

Without a Shell (for example if you stay on free Render a while): run the same commands from your PC against the hosted database using
`set DATABASE_URL=...` (see the Windows block in `docs/DEPLOY_CLOUD.md`, Option B). That needs the database's **external** connection string.

Honest limits: the adapters were written from the provider's documentation and tested against mock responses; `provider-check` is how you
confirm real responses parse before you rely on them. The scanner shows only games that have not kicked off, and only as good as the history.

## 3. Odds board and "edge" (price comparison)

What exists: `ODDS_PROVIDER=api_football` records the provider's **pre-match** odds from its listed bookmakers (refreshed about daily by the
provider), stores history, marks stale prices, and compares to the model's fair odds. Steps: set `ODDS_PROVIDER=api_football`, run
`python -m app.cli odds`, open the odds board, and review which bookmakers and markets appear (Administration > Bookmakers lets you approve
which ones are shown and import odds from an **authorised** source via `odds-import`).

Limits you must plan around:
* It does **not** give a Bet9ja or SportyBet price unless the provider lists them for your leagues.
* **Five-minute markets** ("no goal 0-5'", "level at 5'") are rarely offered pre-match by public odds feeds. If no listed bookmaker prices them,
  the board stays empty for these markets and no "edge" is shown. The app never invents a price: it shows only recorded odds, labelled with age.
* Odds that are truly live (in-play, second-by-second) need a different, usually enterprise, feed (for example a sportsbook-data supplier).
  Price it by asking suppliers for a quote; it is typically far above the API-Football tiers.

Budget line: **$0 extra** if you use API-Football's odds within your plan (confirm the odds endpoint is included in the tier you buy), or a
**quote** for an enterprise odds feed. Decide whether the product needs odds at all at launch: the scanner and ticket do not depend on them.

## 4. Real booking codes: the bookmaker converter

> The full step-by-step playbook (research findings, the pitch, outreach, what to ask, contract points, build and go-live) is in
> [`BOOKMAKER_INTEGRATION_PLAYBOOK.md`](BOOKMAKER_INTEGRATION_PLAYBOOK.md). The summary below is the short version.

This is the part money alone cannot buy: it needs each bookmaker's agreement.

Status: Bet9ja, SportyBet, BetKing, MSport, 1xBet, Betway and BetPawa are registered but **not connected**. I found no public booking-code API
for them and I deliberately do not use unofficial endpoints, scraping or CAPTCHA bypasses (they break, can breach terms, and are not
acceptable for a public product).

1. **Contact each bookmaker's business/affiliate/partnerships team** (start with the two or three your users use most). Ask for: official
   documentation and a sandbox for (a) reading a booking code, (b) searching fixtures with markets and odds, (c) creating a booking code;
   authentication, rate limits; whether a third party may create codes for its users; the market and outcome identifiers (so the exact same
   bet can be created); and commercial terms (many want an affiliate or B2B agreement).
2. **A short message you can send:** "We run First5Minute, a football-analytics service for the first five minutes of a match. Players pick
   games and want to load the same selections on your platform. Do you offer an official API or partnership that lets us (1) read a booking
   code, (2) look up fixtures/markets/odds, and (3) create a booking code, with a sandbox? We never place bets or hold funds."
3. **When you have documentation:** the work is to fill in that bookmaker's three methods in
   `backend/app/booking_converter/adapters/real.py` (see `docs/BOOKING_CODE_CONVERTER.md`). Everything else (matching, screens, safety, tests)
   exists. Expect roughly a few days to a couple of weeks of developer time per bookmaker once the documentation and sandbox arrive; the wait
   for the agreement is the unpredictable part.
4. **Switch it on:** set that bookmaker's API credentials in Render's environment (the adapter reads them from env vars), turn
   `BOOKING_CONVERTER_DEMO` off, run `doctor`, test with real codes in the sandbox, then go live bookmaker by bookmaker.
5. **Until a bookmaker is connected,** players cannot pick it on the ticket page (it shows "not connected yet"). A "Copy ticket as text"
   button (games, markets and the model's estimates, no bookmaker needed) so the player can recreate the slip by hand now exists on the
   ticket page and works without any bookmaker.

Budget: **unknown until quoted** (partner fees, revenue share or minimum volumes are the bookmaker's to set) plus developer time per
integration. This is the biggest unknown in your launch cost.

## 5. Payments (subscriptions)

1. Paystack: create a business account and complete KYC (you need a registered business, section 7).
2. Render environment: `PAYMENT_PROVIDER=paystack`, `PAYSTACK_SECRET_KEY=` (live secret key; type it in the form). Webhook URL in the Paystack
   dashboard: `https://YOUR-DOMAIN/api/v1/webhooks/paystack`.
3. Set plan prices in Administration > Plans. Test one small real payment, a failed card, a renewal and a cancellation.
4. In production the app refuses `PAYMENT_PROVIDER=demo`.

**Cost:** no monthly fee that I found; per transaction Paystack lists 1.5 % + ₦100 for local channels, the ₦100 waived under ₦2,500, and a
₦2,000 cap per transaction; international cards cost more (about 3.9 % + ₦100 in the sources I saw). Verify at support.paystack.com.

## 6. Email

Real sign-up verification and password reset need email delivery. Choose an email provider (many have a free tier that covers early volume;
check the one you pick), verify your sending domain (SPF/DKIM records at your domain registrar), then set in Render: `EMAIL_BACKEND=smtp`,
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` (typed into the form), `EMAIL_FROM`. Send yourself a test registration.
In `ENVIRONMENT=production` the app refuses `EMAIL_BACKEND=console`.

## 7. Legal and compliance (start now; I am not a lawyer)

* Register the business (in Nigeria, the Corporate Affairs Commission) and open a business bank account: needed for Paystack and any
  bookmaker agreement.
* **Ask a Nigerian gaming/technology lawyer** these questions in writing before launch: (1) does a betting-analytics/prediction subscription
  with booking-code generation need any licence or registration, given the product never takes bets, holds funds or sets odds; (2) what
  advertising and responsible-gambling rules apply to promoting it; (3) what is required for personal-data handling under the Nigeria Data
  Protection Act (privacy policy, lawful basis, a data-protection officer or registration thresholds); (4) wording of terms of service and
  the "estimates, not guarantees" disclosures.
* Context I found while researching, to bring to that conversation: operators of sports betting in Nigeria need national and state licences,
  with fee figures that differ across sources and appear to have changed recently (older articles cite about ₦2m; a 2026 guide cites much
  higher figures under a different framework). These apply to **operators**; whether they touch a service like yours is exactly the question
  for the lawyer. None of the sources I found answered it.
* The app already carries 18+ notices, "estimates, not guarantees" wording and a responsible-gambling note, never asks for bookmaker
  credentials and never places bets. Keep it that way, and never market it as guaranteed or risk-free.
* Publish a privacy policy, terms and a contact address before taking money.

## 8. The production switch (last step)

In Render, on the API and the worker: `ENVIRONMENT=production`; remove `BOOKING_CONVERTER_DEMO`; `PAYMENT_PROVIDER=paystack`;
`EMAIL_BACKEND=smtp`; a real `SECRET_KEY` (already generated); `COOKIE_SECURE=true`. The app **refuses to start** in production if any of
these is unsafe. Then run `python -m app.cli doctor` (0 FAIL), register a real test user, buy a plan with a real card, generate a ticket,
and check the Sentry and uptime alerts fire.

---

## Cost summary

Monthly running cost, minimum viable public launch (real games, payments, email, no live converter):

| Item | Monthly (USD, verify) |
|---|---|
| Render API Starter | about 7 |
| Render worker Starter | about 7 |
| Render Postgres Basic-256MB (+ storage) | about 6 + a little |
| Redis (free tier to start) | 0 |
| API-Football Pro / Ultra / Mega | about 19 / 29 / 39 |
| Vercel (paid, once commercial) | about 20 per user (my recollection; verify) |
| Email (free tier to start), Sentry (free tier), uptime monitor (free tier) | 0 to start |
| **Rough total** | **about 40 to 70 per month** with Pro or Ultra, before domain and taxes |
| Paystack | 1.5 % + ₦100 per local transaction (cap ₦2,000) |

One-off and unpriced items (get quotes): domain (yearly), company registration, **lawyer's opinion**, and **each bookmaker integration**
(partner terms plus developer time). If you need a true live-odds feed: a supplier quote. Marketing and support are outside this list.

If instead you want the cheapest possible launch: the scanner (paid football data) + payments + email, with the converter marked
"coming soon" (and the copy-as-text fallback above, once built), which is roughly the table above.
