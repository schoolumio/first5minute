# Put First5Minute online without your PC (free Render + Vercel, upgrade later)

Result: a permanent `https://....vercel.app` link for your team that works while your PC is off. You only click through two dashboards;
no Command Prompt is needed.

| Piece | Where | Free-tier behaviour |
|---|---|---|
| Website (Next.js) | **Vercel** | free "Hobby" plan, always on |
| API | **Render** web service | **sleeps after ~15 idle minutes**, about a minute to wake |
| Database (Postgres) | **Render** | free, but **deleted ~30 days after creation** unless you upgrade it first |
| Redis | **Render** Key Value | free, not persistent (it only holds rate-limit counters and converter sessions) |
| Scheduled jobs (worker) | none on free | the demo data refreshes itself whenever the API wakes up and finds it older than 24 hours |

Everything on the Render side is described in `render.yaml` at the repo root, so Render builds it in one go. It was prepared and checked as
configuration plus unit tests (and a measured fresh start-up: about 215 MB peak, inside the free 512 MB); it could **not** be deployed from
the development sandbox. Treat your first run as the test and send me any error text. Plans, prices and limits change: check
render.com/pricing and vercel.com/pricing.

What you will have at the end: the scanner, ticket builder and converter running on **demo data and fictional demo bookmakers** (every code
labelled `DEMO-`), exactly like your local setup. Live matches and real booking codes are separate steps (see `docs/GO_LIVE.md`,
sections 3 and 5).

---

## Part 0. Before you start (about 10 minutes)

1. **A GitHub login that can read `schoolumio/first5minute`.** If you are not an owner of the `schoolumio` organisation, ask an owner to
   approve Render and Vercel when they ask for access, or fork the repository into your own account and use the fork.
2. Decide the branch: use `claude/busy-edison-qgb9ta` (the latest work), or merge it into `main` first.
3. Make up an **admin email and a strong password** (12+ characters, letters and digits). Keep them in a password manager. You will
   type them into a form in Part 1. Never paste them into chat or a file.
4. Accounts: sign up at render.com and vercel.com **using "Continue with GitHub"**. Either may ask for a card even for free services.

## Part 1. Render: database, Redis and the API (about 10 minutes of clicking, then waiting)

1. In Render click **New +** then **Blueprint**.
2. Choose the `first5minute` repository (click **Connect**), then pick your branch.
3. Render reads `render.yaml` and shows what it will create: a database `f5m-db`, Redis `f5m-redis`, and the web service `f5m-api`.
   All three should say **Free**.
4. Fill the four boxes it asks for:
   * `BOOTSTRAP_ADMIN_EMAIL`: your admin email.
   * `BOOTSTRAP_ADMIN_PASSWORD`: your admin password.
   * `FRONTEND_URL` and `CORS_ORIGINS`: type `https://placeholder.example.com` in both for now (you fix them in Part 4).
5. Click **Apply** (or Deploy Blueprint). The first build takes several minutes. Watch `f5m-api` until it says **Live**.
6. Open `f5m-api` and copy its address at the top, like `https://f5m-api-xxxx.onrender.com`.
7. **Check it works:** open `https://f5m-api-xxxx.onrender.com/healthz` in your browser. You should see `{"status":"ok"}`.
8. Open the **Logs** tab. About a minute after it goes live (free instances are slow) you should see a block containing
   `"admin": "created"` and `"demo_data": "loaded"`. If you see `bootstrap failed`, read the lines above it (usually a weak password).

## Part 2. Vercel: the website (about 5 minutes)

1. In Vercel click **Add New...** then **Project**, and import `first5minute`.
2. **Root Directory:** click **Edit** and choose `frontend`. The framework should read **Next.js**.
3. Open **Environment Variables** and add exactly one:
   * Name `BACKEND_URL`, value = the Render address from Part 1 step 6 (no `/` at the end).
   * This must be set **before** the first deploy. Vercel bakes it in during the build.
4. Click **Deploy**. When it finishes you get a link like `https://first5minute-xxxx.vercel.app`. Open it: the landing page loads.

## Part 3. Connect the two (2 minutes)

In Render open `f5m-api`, then **Environment**. Change both values to your Vercel address, then **Save, rebuild, and deploy**:

* `FRONTEND_URL` = `https://first5minute-xxxx.vercel.app`
* `CORS_ORIGINS` = `https://first5minute-xxxx.vercel.app`

## Part 4. First sign-in

1. Open your Vercel link and click **Sign in**. Use the admin email and password from Part 1.
   The first request after the API has been idle can take up to a minute. If you see an error, wait 30 seconds and refresh.
2. You should see the purple "Demo environment" banner and the scanner full of demo games. Add three picks, open **My ticket**, choose
   **Demo Book Alpha** and generate a code (it will start with `DEMO-`).

## Part 5. Add your team

1. Send the Vercel link; teammates click **Create an account** and register. Emails are written to the Render logs on this setup (they are
   not delivered), so the teammate stays "unverified".
2. You sign in, open **Administration > Users**, click **Verify** on their row and choose a plan (for example `pro`) in the Plan box.
3. They can now use the scanner and ticket builder.

## Living with the free tier (read this before the demo)

* **Cold starts.** After ~15 idle minutes the API sleeps. The next person waits up to a minute and may see an error on first click:
  tell them to wait and refresh. **Open the link yourself 2 minutes before any live demo or investor call.**
* **Keeping it awake (optional).** A free uptime monitor that opens `https://f5m-api-xxxx.onrender.com/healthz` every 5 minutes keeps it
  awake. One always-on free service fits inside Render's monthly free hours, but Render's rules can change, so confirm. If it never sleeps it
  also never restarts, so the demo data would go stale after a few days: in Render open `f5m-api` > **Manual Deploy** > **Restart service**
  (or Deploy latest commit) to refresh it.
* **Demo data refresh.** On every start, if the demo data is older than 24 hours the API reloads it (takes a minute or two on a free instance).
  A refresh removes demo rows, including teammates' saved demo matches. Tickets live in each person's browser and are not affected.
* **Database expiry (the important one).** In Render open `f5m-db` and note the expiry date. **Upgrade it before that date** (Part 6) or the
  data is deleted. Put a reminder in your calendar for day 20.
* **No shell.** Free web services have no Shell tab, so use the admin page for users and the Logs tab for diagnostics.

## Part 6. When the client pays: moving to paid (no rebuild, no data loss)

Do these in this order, in the Render dashboard:

1. **Database first:** `f5m-db` > **Settings** (or Info) > change the instance type / **Upgrade** to a paid plan. It upgrades in place and
   keeps your data. This removes the 30-day expiry.
2. **API:** `f5m-api` > **Settings** > **Instance Type** > pick a paid type (for example Starter). It stops sleeping.
3. **Worker (scheduled scans, settlement, renewals):** in `render.yaml` delete the `#` comment marks in front of the `f5m-worker` block, change
   `RUN_WORKER` on `f5m-api` to `"false"` (it already is), commit, and in Render open the Blueprint and **Manual sync**. Worker is a paid type.
4. **Redis:** the free one is fine to start; upgrade it if you want it to survive restarts.
5. **Vercel:** the free Hobby plan is for non-commercial use. When customers use the site, move to a paid Vercel plan (read its terms) and
   attach your domain: project > **Settings > Domains**, then update `FRONTEND_URL` and `CORS_ORIGINS` in Render to the new address.
6. **Backups:** confirm the backup/retention of the database plan you chose, and test a restore once.

Going from demo to genuinely live is a separate list (see `docs/GO_LIVE.md` section 4): `ENVIRONMENT=production` (the app then refuses demo
switches), remove `BOOKING_CONVERTER_DEMO`, a football-data provider and key (typed only into Render's Environment form), real SMTP email,
Paystack live keys, and an official integration per bookmaker for real booking codes.

## If something goes wrong

| Symptom | Likely cause and fix |
|---|---|
| Render rejects `render.yaml` | send me the exact message: a field or plan name may have changed |
| `f5m-api` fails to deploy | open **Logs**; a database/migration/env error is printed there |
| `/healthz` does not answer | the instance is waking up (wait a minute) or the deploy failed (check Logs) |
| Vercel site loads but sign-in says "Network error" or 502 | `BACKEND_URL` is wrong, has a trailing `/`, or was added after the first build. Fix it, then in Vercel **Deployments > Redeploy** |
| Sign-in works but a teammate sees "Verify your email" | click **Verify** for them in Administration > Users (Part 5) |
| Cannot sign in as admin | the admin values were empty or the password was weak; look for `bootstrap` in the API Logs, fix the values, restart. An existing account is never reset |
| Scanner empty right after deploy | demo data loads in the background; wait a minute and refresh |
| Scanner empty days later | the data is older than the games; restart the API (see "Keeping it awake") |
| App crashes with "out of memory" | the free 512 MB is too small for your usage: upgrade the API instance (Part 6 step 2) |

Changing the code later: push to the branch and both services redeploy automatically.

---

## Option B (experimental): everything on Vercel as one project with two services

`vercel.json` at the repo root declares two services: `web` (Next.js, `frontend/`) and `api` (FastAPI, `backend/`), and routes `/api/v1/*` to
`api` and everything else to `web`. Import the repo in Vercel with **Root Directory = the repository root** (not `frontend`; do not set
`BACKEND_URL`). Browser calls to `/api/v1` then reach the API directly, and no service calls another, so there are no bindings.
Not deployed or run from the development sandbox. Read the limits before choosing this over Parts 1-3:

* **Bundle size (likely blocker).** The API's dependencies measure about 328 MB installed (scipy 138, numpy 56, scikit-learn 46).
  As I recall, Vercel's Python functions are limited to about 250 MB unzipped; verify on vercel.com/docs. If the build fails on size, the fix is a
  slimmer API dependency set (lazy-loading the ML modules and replacing the two scipy calls in `app/engine/poisson.py`), which is code work.
* **No worker, no beat.** Celery cannot run on Vercel, so scheduled scans, settlement and renewals do not run. Demo data does not
  refresh itself either.
* **No start-up steps.** Migrations and `bootstrap` do not run on Vercel. Run them once from your PC against the database (below).
* **Database and Redis must be external** (Render's, Neon or Upstash via the Vercel Marketplace). Redis is required, not optional: serverless
  instances do not share memory, and the ticket flow keeps its state between requests in Redis.
* **Environment variables** (Project > Settings > Environment Variables, shared by both services): `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`
  (64 random hex characters), `ENVIRONMENT=staging`, `COOKIE_SECURE=true`, `FRONTEND_URL` and `CORS_ORIGINS` (your Vercel address),
  `FOOTBALL_PROVIDER=demo`, `ODDS_PROVIDER=none`, `PAYMENT_PROVIDER=none`, `EMAIL_BACKEND=console`, `BOOKING_CONVERTER_ENABLED=true`,
  `BOOKING_CONVERTER_DEMO=true`.

One-off database setup from your PC (Windows Command Prompt; use the connection string your database provider shows, and never share it):

```bat
call "C:\Users\User\Downloads\first5minute-claude-busy-edison-qgb9ta (3)\first5minute-claude-busy-edison-qgb9ta\backend\.venv\Scripts\activate"
cd /d "NEWFOLDER\backend"
set DATABASE_URL=PASTE-YOUR-DATABASE-URL-HERE
set REDIS_URL=PASTE-YOUR-REDIS-URL-HERE
set FOOTBALL_PROVIDER=demo
set BOOTSTRAP_ADMIN_EMAIL=you@example.com
set BOOTSTRAP_ADMIN_PASSWORD=YourStrongPassword1
alembic upgrade head
python -m app.cli bootstrap
```

`vercel dev` runs both services locally. To refresh stale demo data later, repeat the last line with `set DEMO_REFRESH_HOURS=24`.
