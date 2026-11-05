# Put First5Minute online without your PC (Render + Vercel)

Result: a permanent `https://....vercel.app` link for your team. Nothing runs on your computer; you only click through two dashboards.

| Piece | Where | Why there |
|---|---|---|
| Website (Next.js) | **Vercel** | Vercel is built for Next.js |
| API + background worker | **Render** | the API must stay running and the worker runs scheduled jobs; Vercel's functions cannot do either |
| Database (Postgres) and Redis | **Render** | managed, backed up, created by the same file |

All the backend pieces are described in `render.yaml` at the repo root, so Render builds them in one go. This was prepared and checked as
configuration and unit tests only: it could not be deployed from the development sandbox. Treat the first run as a test and send me any
error text.

Costs: this setup uses paid Render plans on purpose (a free web service sleeps after idle minutes, and a free database is deleted after
about 30 days). Check current prices at render.com/pricing and vercel.com/pricing before you click. Vercel's free "Hobby" plan is meant for
non-commercial use; read its terms if investors or customers will use the link.

---

## 0. Before you start (10 minutes)

1. **The code must be on GitHub where both services can read it.** It is in `schoolumio/first5minute`, branch `claude/busy-edison-qgb9ta`.
   You need a GitHub login that can read that repository. If you are not an owner of the `schoolumio` organisation, ask an owner to
   approve Render and Vercel when they ask for access, or fork the repository into your own account and use the fork.
2. Optional but wise: merge the branch into `main` first so deploys follow `main`. Otherwise just choose the branch name in step 1.
3. Make up an **admin email and a strong password** (12+ characters, letters and digits). You will type them into a form in step 1; never
   put them in chat or in a file.

## 1. Render: database, Redis, API, worker

1. Sign up at render.com with GitHub.
2. **New > Blueprint**, pick the `first5minute` repository and the branch. Render reads `render.yaml` and lists 4 things: database
   `f5m-db`, Redis `f5m-redis`, web service `f5m-api`, worker `f5m-worker`.
3. It asks for the values marked "sync: false":
   * `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`: your admin login from step 0.
   * `FRONTEND_URL` and `CORS_ORIGINS`: type `https://placeholder.example.com` for now; you fix them in step 3.
4. Click **Apply**. The first build takes several minutes. When `f5m-api` shows **Live**, open its page and copy its address, like
   `https://f5m-api-xxxx.onrender.com`. Open `https://f5m-api-xxxx.onrender.com/healthz`: it should answer `{"status":"ok"...}`.
5. First start: the API creates the tables, then (in the background, about a minute) creates your admin account and loads the **demo**
   data. You can watch it in the service's **Logs**: look for `"admin": "created"` and `"demo_data": "loaded"`.

## 2. Vercel: the website

1. Sign up at vercel.com with GitHub. **Add New > Project**, import `first5minute`.
2. **Root Directory:** click Edit and choose `frontend`. Framework should read "Next.js".
3. **Environment Variables:** add one, `BACKEND_URL` = the Render API address from step 1.4 (no trailing slash).
   It must be set *before* the first build, because Vercel bakes it into the proxy rules.
4. **Deploy.** When it finishes you get `https://first5minute-xxxx.vercel.app`. Open it: the landing page loads.

## 3. Tell the API its public address (2 minutes)

In Render, open `f5m-api` > **Environment** and set both to your Vercel address, then **Save** (it redeploys):

* `FRONTEND_URL` = `https://first5minute-xxxx.vercel.app`
* `CORS_ORIGINS` = `https://first5minute-xxxx.vercel.app`

Do the same two values on `f5m-worker`. Then sign in at your Vercel link with the admin email and password. The sidebar should show
"Scanner live" and the purple demo banner; the scanner lists demo games, and tickets can be built on the demo bookmakers.

## 4. Add your team

Teammates register themselves on your Vercel link; you then approve them from the admin page.
Email verification is switched to `console` (emails are written to the logs, not sent), so for a team test do this: after a teammate
registers, sign in as admin, open **Administration > Users**, click **Verify** on their row, and pick their plan (for example `pro`). When you are ready for real mail, set `EMAIL_BACKEND=smtp` and the `SMTP_*`
values (see `.env.production.example`).

## 5. Custom address (optional)

Vercel > your project > **Settings > Domains** to attach your own domain; update `FRONTEND_URL` and `CORS_ORIGINS` in Render to match.

## What this does and does not give you

* The scanner, ticket builder and converter run on **demo data and fictional demo bookmakers** (every code is labelled `DEMO-`), exactly
  like the local setup. Live matches need a football-data plan; real booking codes need an official bookmaker integration
  (see `docs/GO_LIVE.md`, sections 3 and 5).
* When you go truly live: `ENVIRONMENT=production`, remove `BOOKING_CONVERTER_DEMO`, set `FOOTBALL_PROVIDER=api_football` with its key
  (type it only into Render's environment form), real SMTP, Paystack live keys. The app refuses to start in production with demo switches
  on. Run `python -m app.cli doctor` from Render's **Shell** tab (paid services have one).
* Backups: Render's paid Postgres plans keep backups; confirm the retention on the plan you pick.

## If something goes wrong

| Symptom | Likely cause |
|---|---|
| Vercel site loads but sign-in says "Network error" / 502 | `BACKEND_URL` is wrong or was added after the first build: fix it, then **Redeploy** |
| `f5m-api` stuck on "Deploying" | open Logs; a migration or environment error is printed there |
| Scanner is empty right after the first deploy | the demo data loads in the background for about a minute; refresh |
| Cannot sign in as admin | `BOOTSTRAP_ADMIN_*` were empty or the password was too weak (see the `bootstrap` line in the API logs). Set them and redeploy; an existing account is never reset |
| Render rejects `render.yaml` | send me the exact message; plan names or field names may have changed |

Changing the code later: push to the branch; both services redeploy automatically.
