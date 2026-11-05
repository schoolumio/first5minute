"""Readiness checker: tells you, in plain words, what is LIVE and what is not on this deployment.

``python -m app.cli doctor``. Exit status is non-zero if anything is FAIL. Secrets are never printed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.config import DEV_SECRET, Settings, get_settings

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


@dataclass
class Check:
    area: str
    status: str
    detail: str


def _strict(prod: bool) -> str:
    """A problem that is blocking in production but only a warning elsewhere."""
    return FAIL if prod else WARN


def config_checks(s: Settings) -> list[Check]:
    c: list[Check] = []
    prod = s.is_production
    note = "" if prod else " (not production: demo banners and relaxed checks)"
    c.append(Check("Environment", PASS if prod else INFO, f"ENVIRONMENT={s.environment}{note}"))

    weak = s.secret_key == DEV_SECRET or len(s.secret_key) < 32
    c.append(Check("Secret key", _strict(prod) if weak else PASS,
                   "SECRET_KEY is the development default or shorter than 32 characters." if weak else "SECRET_KEY is set."))

    if s.frontend_url.startswith("https://") and not s.cookie_secure:
        c.append(Check("Cookies", _strict(prod), "FRONTEND_URL is https but COOKIE_SECURE is not true."))
    elif prod and not s.cookie_secure:
        c.append(Check("Cookies", FAIL, "COOKIE_SECURE must be true in production."))
    else:
        c.append(Check("Cookies", PASS, f"COOKIE_SECURE={s.cookie_secure}"))

    local = "localhost" in s.frontend_url or "127.0.0.1" in s.frontend_url
    why = " (emails and payment redirects would point at your own computer)" if local else ""
    c.append(Check("Public address", _strict(prod) if local else PASS, f"FRONTEND_URL={s.frontend_url}{why}"))

    if s.email_backend == "smtp":
        c.append(Check("Email", PASS if s.smtp_host else FAIL, "SMTP host " + ("set." if s.smtp_host else "missing (SMTP_HOST).")))
    else:
        c.append(Check("Email", _strict(prod),
                       f"EMAIL_BACKEND={s.email_backend}: verification and reset emails are NOT delivered to users."))

    if s.football_provider == "demo":
        c.append(Check("Football data", WARN, "FOOTBALL_PROVIDER=demo: fictional fixtures. NOT live data."))
    else:
        key = bool(s.api_football_key if s.football_provider == "api_football" else s.sportmonks_token)
        scope = bool(s.football_league_ids) or s.football_allow_all_leagues
        c.append(Check("Football data", PASS if key and scope else FAIL,
                       f"{s.football_provider}: key {'set' if key else 'MISSING'}, "
                       f"league allowlist {'set' if scope else 'MISSING (FOOTBALL_LEAGUE_IDS)'}. "
                       "Run `provider-check` to confirm your plan can read today's matches."))

    odds = {
        "none": (INFO, "ODDS_PROVIDER=none: no odds are shown (nothing is invented)."),
        "demo": (WARN, "ODDS_PROVIDER=demo: synthetic prices, testing only."),
        "api_football": (INFO, "ODDS_PROVIDER=api_football: pre-match odds only, refreshed about daily by the provider. "
                               "Verify that five-minute markets exist before relying on it."),
    }[s.odds_provider]
    c.append(Check("Odds", *odds))

    if s.payment_provider == "none":
        c.append(Check("Payments", INFO, "PAYMENT_PROVIDER=none: checkout is off."))
    elif s.payment_provider == "demo":
        c.append(Check("Payments", _strict(prod), "PAYMENT_PROVIDER=demo is a simulator."))
    elif not s.paystack_secret_key:
        c.append(Check("Payments", FAIL, "Paystack secret key missing."))
    else:
        test = s.paystack_secret_key.startswith("sk_test")
        c.append(Check("Payments", PASS, "Paystack " + ("TEST keys (no real money)." if test else "LIVE keys.")))
    return c


def converter_checks(s: Settings) -> list[Check]:
    from app.booking_converter.adapters.registry import all_adapters

    if not s.booking_converter_enabled:
        return [Check("Booking converter", INFO, "Switched off (BOOKING_CONVERTER_ENABLED=false).")]
    adapters = [a for a in all_adapters().values() if not a.hidden]
    real = [a for a in adapters if not a.is_demo]
    decode = [a.name for a in real if a.capabilities.can_decode and a.available()]
    generate = [a.name for a in real if a.capabilities.can_generate and a.available()]
    demo = [a.name for a in adapters if a.is_demo]
    c: list[Check] = []
    if generate:
        c.append(Check("Booking converter", PASS, "REAL code creation connected for: " + ", ".join(generate) + "."))
    else:
        c.append(Check("Booking converter", WARN, "No real bookmaker integration is connected: real booking-code conversion is NOT live."))
    if decode and not generate:
        c.append(Check("Converter (read-only)", INFO, "Can read codes from: " + ", ".join(decode) + " (no code creation)."))
    if s.booking_converter_demo or demo:
        names = ", ".join(demo) if demo else "BOOKING_CONVERTER_DEMO=true"
        c.append(Check("Converter demo", _strict(s.is_production), f"Demo bookmakers are ON ({names}): fictional, labelled DEMO."))
    if s.football_provider == "demo":
        c.append(Check("Ticket builder games", WARN, "Games are fictional (demo)."))
    else:
        c.append(Check("Ticket builder games", PASS, "Games come from your football data provider."))
    return c


def io_checks(s: Settings) -> list[Check]:
    from sqlalchemy import text

    from app.core.database import SessionLocal

    c: list[Check] = []
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[2]
        cfg = Config(str(root / "alembic.ini"))
        cfg.set_main_option("script_location", str(root / "alembic"))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        if current == head:
            c.append(Check("Database", PASS, f"Connected. Schema version {current}."))
        else:
            c.append(Check("Database", FAIL, f"Schema is at {current} but the code expects {head}: run `alembic upgrade head`."))
    except Exception as exc:  # noqa: BLE001 - report, never crash the checker
        c.append(Check("Database", FAIL, f"Cannot use the database: {type(exc).__name__}"))
    try:
        import redis

        redis.Redis.from_url(s.redis_url, socket_timeout=1, socket_connect_timeout=1).ping()
        c.append(Check("Redis", PASS, "Connected (rate limits and converter sessions are shared across workers)."))
    except Exception:  # noqa: BLE001
        c.append(Check("Redis", _strict(s.is_production),
                       "Not reachable: the app falls back to memory, which breaks rate limits and converter sessions "
                       "when more than one worker runs."))
    return c


def run_all(s: Settings | None = None, with_io: bool = True) -> list[Check]:
    s = s or get_settings()
    return config_checks(s) + converter_checks(s) + (io_checks(s) if with_io else [])


def render(checks: list[Check]) -> str:
    width = max(len(c.area) for c in checks)
    lines = [f"[{c.status:<4}] {c.area:<{width}}  {c.detail}" for c in checks]
    fails = sum(c.status == FAIL for c in checks)
    warns = sum(c.status == WARN for c in checks)
    verdict = ("Fix every FAIL before sharing this deployment." if fails
               else "No blocking problems. Read each WARN: it names something that is NOT live.")
    return "\n".join(lines + ["", f"{fails} FAIL, {warns} WARN. {verdict}"])
