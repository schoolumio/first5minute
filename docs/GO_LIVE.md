# Going live: a link your team can open

Read this first: what "live" can and cannot mean today.

> **No PC, no server to manage?** Use [`docs/DEPLOY_CLOUD.md`](DEPLOY_CLOUD.md): website on Vercel, API/database/worker on Render, one blueprint file (`render.yaml`).

| Part | Can be live now? | What it needs |
|---|---|---|
| Website, sign-in, accounts, scanner pages | **Yes** | a server (this guide) |
| Live matches (the scanner, and so the games players can add to a ticket) | **Yes, with a paid football-data plan** | `FOOTBALL_PROVIDER=api_football` + a plan that can read today's matches. The free plan only sees yesterday/today/tomorrow and has no recent history |
| Odds on the odds board | **Partly** | `ODDS_PROVIDER=api_football` gives pre-match odds from the provider's bookmakers, refreshed about daily by the provider. It does not give a Bet9ja/SportyBet price, and five-minute markets are unverified |
| **Real booking codes from a bookmaker** | **No, not until you have an official integration** | a partnership/API agreement per bookmaker (see section 5). No public booking-code API was found for the seven bookmakers; unofficial endpoints are not used |
| Payments | Yes, in Paystack TEST mode; live with live keys | Paystack account + webhook URL |

Until a bookmaker is connected the converter and the ticket builder run on the **demo bookmakers** (fictional, every code labelled `DEMO-`).
That is still the right thing to show the team: the whole flow works; only the bookmaker connection is missing.

Run `python -m app.cli doctor` at any point (locally or on the server) for a plain-English list of what is live and what is not.

---

## Path A. A shareable link from your own PC in about 15 minutes

Good for: showing the team today. The link works only while your PC is on and the two windows below stay open, and the address changes
each time. Do not use it for real customers.

**1. Get the newest code.** Download the newest zip of branch `claude/busy-edison-qgb9ta`, extract it, and note the folder (below: `NEWFOLDER`).
Copy your `.env` into it and edit it (`notepad "NEWFOLDER\.env"`). Set at least:

```
ENVIRONMENT=staging
COOKIE_SECURE=true
BOOKING_CONVERTER_ENABLED=true
BOOKING_CONVERTER_DEMO=true
```

**2. Install the tunnel tool (once).** In a normal Command Prompt:

```bat
winget install --id Cloudflare.cloudflared
```

Close the window and open a new one afterwards so the command is found. (No account is needed for a quick tunnel.)

**3. Command Prompt A: the API** (use the virtual environment from your earlier folder; it lives in folder `(3)`):

```bat
call "C:\Users\User\Downloads\first5minute-claude-busy-edison-qgb9ta (3)\first5minute-claude-busy-edison-qgb9ta\backend\.venv\Scripts\activate"
cd /d "NEWFOLDER\backend"
alembic upgrade head
python -m app.cli doctor
uvicorn app.main:app --port 8000
```

(`doctor` may show WARN lines: that is expected on a PC. It must show no FAIL.)

**4. Command Prompt B: the website in production mode** (faster and closer to the real thing than `npm run dev`):

```bat
cd /d "NEWFOLDER\frontend"
npm ci
npm run build
npm run start
```

**5. Command Prompt C: the public link:**

```bat
cloudflared tunnel --url http://localhost:3000
```

After a few seconds it prints an address like `https://something-random.trycloudflare.com`. **That is your link.** Open it yourself first.

**6. Give teammates accounts** (they cannot receive verification emails on a PC). In Command Prompt A's folder, in a fourth window with the
virtual environment active:

```bat
python -m app.cli create-user --email teammate@example.com --password "ChangeMe12345" --plan pro
```

Send each person the link, their email and a temporary password (ask them to change it under Account).

**7. Optional:** put the tunnel address in `.env` as `FRONTEND_URL=https://...` and restart the API window; this only affects links inside emails
and payment redirects.

To stop: close the three windows. The link stops working immediately.

---

## Path B. A proper server with your own address (recommended for sharing beyond a day)

You will have `https://staging.first5minute.com` (or any address you choose) that stays up when your PC is off. The files for this are
already in the project: `docker-compose.prod.yml`, `Caddyfile` and `.env.production.example`.

> The Docker setup was written and checked as configuration only. It could not be built in the development sandbox (no Docker there), so
> treat the first deployment as a test run, and send me any error text you see.

**What you need:** a domain you control; a small Linux server (Ubuntu 24.04; 2 CPU / 4 GB RAM is plenty to start; check the provider's
current prices); about an hour.

**B1. Create the server.** At any VPS provider create an Ubuntu 24.04 server. Choose a data-centre close to your users and note its public
IP address and the root password (or add an SSH key).

**B2. Point your address at it.** In your domain's DNS settings add an **A record**: name `staging`, value = the server's IP. Check from
your PC (it can take a few minutes):

```bat
nslookup staging.first5minute.com
```

It must show your server's IP.

**B3. Connect to the server** from Command Prompt (Windows 10/11 has `ssh` built in):

```bat
ssh root@YOUR.SERVER.IP
```

**B4. Prepare the server** (type these on the server, one at a time):

```bash
apt update && apt install -y unzip ufw
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

**B5. Upload the code.** On your PC download a fresh zip of the branch from GitHub (do not zip a folder where you ran `npm ci`), then in a
**new** Command Prompt on your PC:

```bat
scp "C:\Users\User\Downloads\first5minute-claude-busy-edison-qgb9ta.zip" root@YOUR.SERVER.IP:/root/
```

Back on the server:

```bash
unzip first5minute-claude-busy-edison-qgb9ta.zip
cd first5minute-claude-busy-edison-qgb9ta
```

**B6. Create the settings file** on the server:

```bash
cp .env.production.example .env
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "POSTGRES_PASSWORD=$(openssl rand -hex 16)"
nano .env
```

Paste those two generated values into `.env` and replace every `CHANGE` (domain, `FRONTEND_URL`, `CORS_ORIGINS`). Keep
`ENVIRONMENT=staging`, `BOOKING_CONVERTER_DEMO=true` for a team test. Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

**B7. Start everything** (the first build takes several minutes):

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
```

All services should show `running` (the API shows `healthy`). The database is migrated automatically when the API starts. If something
is not running: `docker compose -f docker-compose.prod.yml logs api` (or `web`, `caddy`) and send me the last lines.

**B8. Create your admin and team accounts, then check readiness:**

```bash
docker compose -f docker-compose.prod.yml exec api python -m app.cli create-admin --email you@example.com
docker compose -f docker-compose.prod.yml exec api python -m app.cli create-user --email teammate@example.com --plan pro
docker compose -f docker-compose.prod.yml exec api python -m app.cli doctor
```

**B9. Open `https://staging.first5minute.com`.** The first load can take a minute while Caddy gets the HTTPS certificate (it needs the DNS
record from B2 and ports 80/443 open). Share the link.

**Updating later:** upload a new zip (B5), unzip over the folder (keep your `.env`), then run the `up -d --build` command again.

**Backups (do this before anyone relies on the data):**

```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U five projectfive | gzip > backup-$(date +%F).sql.gz
```

Run it daily (cron) and copy the files off the server. Test a restore once.

---

## 3. Turning on live football data (so real games appear in the ticket builder)

On the server (or your PC), in `.env`:

```
FOOTBALL_PROVIDER=api_football
API_FOOTBALL_KEY=your-key            # put it only in .env, never in chat
FOOTBALL_LEAGUE_IDS=39               # find ids: python -m app.cli leagues --search premier
```

Restart the API, then run `python -m app.cli provider-check`. If it reports your plan cannot read today's matches, you need a plan that can.
With data flowing, run `python -m app.cli sync` then `scan`: the scanner fills as history is downloaded (see `docs/LOCAL_TESTING.md`,
section 10), and players add those games and the model's analysis to their ticket. Before any bookmaker is connected, tickets can only be
converted on the demo bookmakers.

For odds: set `ODDS_PROVIDER=api_football`, run `python -m app.cli odds`, and inspect the odds board. Do not promote it as "live bookmaker odds":
it is the provider's pre-match data.

## 4. From staging to production

1. Real email: `EMAIL_BACKEND=smtp` with your SMTP provider's settings (verification and password-reset emails depend on it).
2. `ENVIRONMENT=production`; remove `BOOKING_CONVERTER_DEMO=true` (the app refuses to start with it).
3. Paystack live keys and the webhook `https://YOUR-DOMAIN/api/v1/webhooks/paystack`.
4. A football-data plan that matches your needs; `SENTRY_DSN` for error alerts; daily backups copied off-server.
5. Legal review for Nigeria (NLRC, data protection) before promoting anything betting-related.
6. `python -m app.cli doctor` must show **0 FAIL**.

## 5. Getting real booking codes: what to ask each bookmaker

The converter and ticket builder are finished and tested. To make a bookmaker real you need its **official** integration. Contact its
business/partnerships (affiliate or B2B) team and ask for:

* documentation and a sandbox for: (1) reading a booking code, (2) searching fixtures with markets and odds, (3) creating a booking code;
* how authentication works, rate limits, and whether the terms allow a third party to create codes for its users;
* the market/outcome identifiers (so the exact same bet can be created).

When you have that, the work is to fill in that bookmaker's three methods in `backend/app/booking_converter/adapters/real.py`
(see `docs/BOOKING_CODE_CONVERTER.md`). Everything else (matching, the screens, safety rules, tests) is already in place.
I did not use unofficial or scraped endpoints: they can break at any time, can breach a bookmaker's terms and are usually behind bot
protection that must not be bypassed.
