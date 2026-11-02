# Project Five - Architecture & Implementation Plan

## 1. Architecture

A **modular monolith**: one FastAPI service with clear module boundaries, one Next.js web app, and
Celery workers that share the backend codebase.

```
Browser ──► Next.js (UI, /api/v1 proxy) ──► FastAPI ──► PostgreSQL
                                              │  └────► Redis (rate limits, Celery broker)
                       Celery beat ──► Celery workers ──► provider adapters ──► API-Football / Sportmonks / Paystack
```

* The browser only talks to its own origin; Next.js rewrites `/api/v1/*` to FastAPI. Session cookies
  are first-party, httpOnly and `SameSite=Lax`; unsafe requests carry a double-submit CSRF header.
  API clients (Elite) use bearer tokens instead.
* **No secret ever reaches the frontend.** Provider and payment keys live only in backend env vars.

### Module map

| Module | Responsibility |
|---|---|
| `providers/football` | `FootballDataProvider` interface + normalised dataclasses; adapters for API-Football, Sportmonks, DEMO |
| `providers/http` | Token-bucket rate limiter, retries with exponential backoff (429/5xx/network), per-call health log |
| `ingestion` | Idempotent upserts on `(provider, provider_id)`, raw payload archive (hash-deduped), event replacement on corrections with `data_version` bumps, timeline reconciliation |
| `engine/settlement` | Pure functions: score at the cutoff, market settlement, timeline consistency |
| `engine/features` | Leak-free history (`kickoff_at < as_of`), competition baselines, input-version hashing |
| `engine/poisson` | Gamma-Poisson smoothing with recency decay, strength model, Model A and Model B |
| `engine/predictor` | Data quality, uncertainty (delta method on Gamma posteriors), confidence, categorisation |
| `engine/backtest` | Walk-forward evaluation with monthly folds; ROI only from real pre-kickoff odds |
| `scanner` | Scan → predict → persist (immutable) → notify; settlement & re-settlement |
| `services` | Auth, entitlements (server-side plan checks), billing lifecycle, audit, email, settings |

## 2. Five-minute settlement - how the exact cutoff score is established

* Window = first `cutoff_seconds` of first-half match clock (default 300 → 00:00-04:59), measured from
  the **actual** kickoff, so delayed kickoffs are irrelevant.
* Second-precision timestamps are compared exactly. Minute-precision timestamps are converted to a time
  interval using the rule's **minute convention** (`ordinal`: minute 5 = 04:00-04:59; `elapsed`:
  minute 5 = 05:00-05:59). If the interval straddles the cutoff the result is **unresolved** - never guessed.
* Stoppage-time events (`45+2`) and second-half events are outside the window.
* VAR-cancelled / provider-rescinded goals never count; own goals are credited to the opponent (configurable).
* Postponed/cancelled → void. Abandoned/suspended → void unless the window was fully played (rule-configurable).
* A final fixture's goal events must reconcile with its 90-minute score; otherwise its timeline is
  `inconsistent`, it is excluded from features and its predictions settle as `unresolved`.
* Provider corrections replace the event set atomically, bump `fixtures.data_version`, and the
  settlement job re-settles affected predictions (`prediction_outcomes.revision` increments).

Settlement rules are rows in `settlement_rules` (admin-selectable default) because bookmakers differ.

## 3. Prediction engine (baseline)

For each team, the last *N* (default 20) **reliable** matches before kickoff give early goals for/against.
Rates are recency-weighted (half-life 10 matches) and shrunk toward the competition's per-team rate
with prior strength *k* = 8 pseudo-matches (Gamma-Poisson posterior mean). The competition baseline is
itself blended toward a global prior when it has fewer than 40 matches.

```
attack(t)  = scoring_rate(t)  / league_per_team_rate
defence(t) = conceding_rate(t) / league_per_team_rate
λ_home = league_home_rate · attack(home) · defence(away)
λ_away = league_away_rate · attack(away) · defence(home)
Model A: P(no goal) = exp(-(λ_home + λ_away))
Model B: P(level)   = exp(-(λ_home + λ_away)) · I0(2·sqrt(λ_home·λ_away))   (+ 0-0/1-1/2-2/other components)
```

**Confidence** comes from the posterior uncertainty of the four rates (delta method) - not from the
probability itself. **Data quality** depends on minimum team sample, share of reconciled timelines and
competition sample. **Categories**: `qualified` (probability + sample + data-quality thresholds),
`watchlist` (probability only), `below_threshold`, `excluded` (insufficient history - never assigned
a qualifying prediction). All thresholds are admin-configurable.

**Immutability**: predictions are insert-only. A PostgreSQL trigger rejects updates to predictive fields
and deletes (except demo rows); a check constraint enforces `predicted_at < kickoff_at`; a partial
unique index keeps one *current* prediction per fixture and market. New pre-kickoff data creates a new
row and supersedes the old one. Each row stores model version, settlement rule, input-data hash,
probability, components, data quality and confidence.

## 3b. Advanced models (Phase 3)

All candidates are per market and trained on a leak-free dataset (`engine/ml/dataset.py`): one row per
finished fixture with a reconciled timeline; features come from the *same* as-of-kickoff code path as live
predictions; labels are the settled outcome.

| Candidate | What it is |
|---|---|
| `poisson_baseline` | Phase-2 model, unchanged - the reference every candidate must beat |
| `climatology` | training base rate only - what "no information" scores; also a gate |
| `hier_eb_poisson` | **Empirical-Bayes** hierarchical Poisson: league to team partial pooling; the shrinkage strength is fitted by predictive likelihood of observed early-goal counts instead of a fixed constant. (Not a full MCMC Bayesian hierarchy.) |
| `logistic` | L2-regularised logistic regression on 27 pre-kickoff features |
| `lightgbm_residual` | LightGBM with the baseline logit as `init_score`: tiny trees, strong regularisation; learns residuals only, so small samples stay at the baseline |
| `ensemble` | equal-weight mean in logit space of the three above (no fitted weights, hence no extra look-ahead) |
| `+platt` / `+isotonic` | calibration variants: Platt below 800 samples, isotonic above, none below 60 |

**Evaluation (`engine/ml/evaluation.py`)** is expanding-window, out-of-fold: rows are cut into time blocks
snapped to calendar days; each test block is predicted by models trained only on rows that kicked off at least
3h earlier (embargo = match length). Calibrators are fitted only on earlier blocks' out-of-fold predictions.
Every variant is scored on the same rows (Brier, log loss, ECE, precision/recall) and compared with the baseline and
climatology using a **paired bootstrap** of per-match log loss (95% CI).

**Promotion gates** - a model replaces the baseline automatically only if *all* hold: not trained on demo data;
at least `ML_MIN_OOS_SAMPLE` (300) out-of-sample matches; log-loss CI vs baseline entirely below zero; CI vs
climatology entirely below zero; calibration error no worse than max(baseline, 0.03). Otherwise the version is
registered (inactive) with the reasons in its notes. `calibration_status` is `calibrated` only when a calibrated
variant passes the gates, `demo_only` for demo-trained models, else `uncalibrated`. Admins can override via
*Admin > Models* (explicit confirmation, audit-logged) and roll back to the baseline at any time.

**Serving**: the scanner uses the active model per market (joblib artifact in `MODEL_DIR`); if an artifact is missing
or fails, that fixture falls back to the baseline and the prediction says so. Predictions made with a model are new
immutable rows; rolling back or forward never edits history (migration 0003 lets the same model be re-activated).
Confidence labels still derive from the baseline's posterior uncertainty (approximate for ML estimates).

**Honest status on the demo data**: with 131 out-of-sample matches, no candidate beats the baseline
significantly and the base-rate reference scores best, so nothing is promoted. That is the gates working;
real conclusions require real, much larger histories.

## 4. Phase status

| Phase | Status | Notes |
|---|---|---|
| 1. Setup, architecture, database, auth, design system | **Done** | 29-table schema, migrations, cookie+bearer auth, verification, reset, lockout, CSRF, rate limiting, design tokens & components |
| 2. Provider integrations & historical DB | **Done (adapters), pending live verification** | API-Football & Sportmonks adapters built from documentation and tested with mock payloads; **not yet verified against live APIs** (no keys available). Historical backfill command per competition still to add. |
| 3. Statistical engine & backtesting | **Done** | Baseline Poisson A/B plus logistic regression, LightGBM, empirical-Bayes hierarchical Poisson, equal-weight ensemble, Platt/isotonic calibration, walk-forward evaluation with paired-bootstrap significance, promotion gates, model registry/activation/rollback and optional MLflow tracking (see section 3b). Full MCMC Bayesian hierarchical models (PyMC/Stan) are not implemented. |
| 4. Scanner & dashboard | **Done** | Scanner API + UI with filters/sorting, dashboard, match details with charts, prediction history & performance; automatic competition eligibility (coverage tiers, EXCLUDED with reason, admin override); email digests and settlement alerts; weekly performance trend; resumable history backfill. Step-by-step local testing: `docs/LOCAL_TESTING.md`. Not yet done: push/SMS channels, live (in-play) status in the scanner. |
| 5. Odds & assisted links | **Partial** | Odds abstraction, API-Football odds mapping (conservative), bookmaker admin, deep-link templates, execution-adapter interface. Needs an odds source that actually prices five-minute markets. |
| 6. Subscriptions, users, notifications | **Mostly done** | Plans, Paystack checkout/verify/webhook, cancel/expiry, invoices, in-app notifications. Email/push delivery of notifications and Paystack recurring authorisation (auto-renew charge) remain. |
| 7. Admin, security, testing | **Mostly done** | Admin API + UI (users, plans, competitions, providers, jobs, thresholds, rules, models, bookmakers, audit). Remaining: Elite API keys & per-key quotas, 24h cooling-off when raising RG limits. |
| 8. Deployment & monitoring | **Scaffolded** | Dockerfiles, Compose, CI, Sentry hook, JSON logs. Docker images were not built in the development sandbox; cloud deployment not performed. |

## 5. Missing technical requirements / external dependencies

1. **Football data subscription** (API-Football or Sportmonks) with event timelines - coverage and
   timestamp precision vary per league; check before enabling competitions.
2. **Several seasons of real, timestamped history** per competition: the advanced models need on the order of
   thousands of matches before they can credibly beat the baseline. **An odds source that prices five-minute markets** is the next constraint: Few bookmakers/aggregators expose them; without
   one, odds comparison and ROI analysis remain empty (by design).
3. **Authorised sportsbook referral agreements** for deep links; execution APIs require operator approval.
4. **Paystack account** (secret key, webhook URL). For recurring auto-charge, store authorisation codes
   and add a renewal job (currently users renew via checkout).
5. **SMTP / transactional email provider** for verification, reset and notification emails.
6. **Licensing & compliance review** for each target market (Nigeria: NLRC and state lottery boards;
   data-provider redistribution terms; NDPR for personal data).
7. **Hosting**: managed PostgreSQL + Redis, TLS, Sentry project.

## 6. Security & operations

* bcrypt (cost 12, SHA-256 pre-hash), short-lived JWT access tokens, rotating hashed refresh tokens with
  reuse detection, account lockout, per-IP rate limits (Redis, memory fallback).
* Server-side entitlements on every gated endpoint; users can only access their own saved matches, bets
  and notifications (404 on others).
* Parameterised SQL via SQLAlchemy; Pydantic validation; security headers; production config guard.
* Audit log for auth events, admin changes, billing events and job runs.
* Paystack webhooks verified with HMAC-SHA512; amounts and currency re-checked; idempotent processing.
* **Backups**: daily automated snapshots + PITR (7-35 days) on managed PostgreSQL; quarterly restore drills.
* **Retention** (proposed): provider logs 90 days, raw payloads 2 years, audit logs 2 years,
  predictions/outcomes indefinitely (track record), auth tokens purged 30 days after expiry.
  Retention jobs are still to be scheduled.
