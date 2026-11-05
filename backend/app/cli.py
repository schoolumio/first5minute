"""Operational CLI.

  python -m app.cli create-admin --email admin@example.com --password '...'
  python -m app.cli seed-demo [--reset] [--replay-days 14]
  python -m app.cli bootstrap     (idempotent first start: admin + demo data; used by the cloud deployment)
  python -m app.cli sync | scan | settle | backtest | expire
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.database import SessionLocal, utcnow
from app.core.logging import configure_logging
from app.core.security import hash_password, password_policy_errors
from app.models import Role, User


def create_admin(email: str, password: str | None) -> None:
    password = password or getpass.getpass("Password: ")
    errs = password_policy_errors(password)
    if errs:
        sys.exit("Password " + ", ".join(errs))
    with SessionLocal() as db:
        role = db.scalar(select(Role).where(Role.name == "admin"))
        user = db.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(email=email.lower(), password_hash=hash_password(password), role_id=role.id,
                        full_name="Administrator", email_verified_at=utcnow(), notification_prefs={})
            db.add(user)
        else:
            user.role_id, user.password_hash = role.id, hash_password(password)
            user.email_verified_at = user.email_verified_at or utcnow()
        db.commit()
        print(f"Admin ready: {user.email}")


def create_user(email: str, password: str | None, plan: str) -> None:
    from app.models import Plan, Subscription

    password = password or getpass.getpass("Password: ")
    errs = password_policy_errors(password)
    if errs:
        sys.exit("Password " + ", ".join(errs))
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            sys.exit("A user with that email already exists.")
        role = db.scalar(select(Role).where(Role.name == "user"))
        user = User(email=email.lower(), password_hash=hash_password(password), role_id=role.id, full_name=email.split("@")[0],
                    email_verified_at=utcnow(), notification_prefs={})
        db.add(user)
        db.flush()
        if plan != "free":
            p = db.scalar(select(Plan).where(Plan.code == plan))
            db.add(Subscription(user_id=user.id, plan_id=p.id, status="active", current_period_start=utcnow(),
                                current_period_end=utcnow() + timedelta(days=30), payment_provider="manual"))
        db.commit()
        print(f"User ready: {user.email} (plan: {plan}, email verified)")


def reset_demo(db) -> None:
    """Remove all demo-flagged data (never touches live provider data)."""
    db.execute(text("SET LOCAL projectfive.allow_prediction_delete = 'on'"))
    db.execute(text("DELETE FROM predictions WHERE is_demo"))
    db.execute(text("DELETE FROM notifications WHERE body LIKE '%[DEMO DATA]%'"))
    for table in ("saved_matches", "bet_tracking", "odds_snapshots"):
        db.execute(text(f"DELETE FROM {table} WHERE fixture_id IN (SELECT id FROM fixtures WHERE is_demo)"))  # noqa: S608 - constant table names
    db.execute(text("DELETE FROM team_match_stats WHERE fixture_id IN (SELECT id FROM fixtures WHERE is_demo)"))
    db.execute(text("DELETE FROM fixtures WHERE is_demo"))
    db.execute(text("DELETE FROM bookmakers WHERE is_demo"))
    db.execute(text("DELETE FROM seasons WHERE competition_id IN (SELECT id FROM competitions WHERE is_demo)"))
    db.execute(text("DELETE FROM competitions WHERE is_demo"))
    db.execute(text("DELETE FROM teams WHERE is_demo"))
    db.execute(text("DELETE FROM model_metrics WHERE is_demo"))
    db.execute(text("DELETE FROM provider_payloads WHERE provider = 'demo'"))
    db.commit()


def bootstrap() -> dict:
    """Idempotent first-start setup for hosts without a shell (Render, Railway, ...). Safe to run on every deploy.

    * creates the admin from BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD, only if that email has no account yet
      (an existing account is never touched, so a changed password is not silently reset);
    * loads the demo data once, when FOOTBALL_PROVIDER=demo and none exists yet.
    """
    from app.models import Fixture

    s = get_settings()
    out: dict = {"admin": "not configured", "demo_data": "not needed"}
    if s.bootstrap_admin_email and s.bootstrap_admin_password:
        with SessionLocal() as db:
            exists = db.scalar(select(User).where(User.email == s.bootstrap_admin_email.lower())) is not None
        if exists:
            out["admin"] = "already exists"
        else:
            create_admin(s.bootstrap_admin_email, s.bootstrap_admin_password)
            out["admin"] = "created"
    if s.demo_mode:
        with SessionLocal() as db:
            have = db.scalar(select(Fixture.id).where(Fixture.is_demo.is_(True)).limit(1)) is not None
        if have:
            out["demo_data"] = "already loaded"
        else:
            seed_demo(False, 14)
            out["demo_data"] = "loaded"
    return out


def seed_demo(reset: bool, replay_days: int) -> dict:
    """Load synthetic DEMO data and replay the pipeline over recent days.

    The replay runs the real scanner with a simulated clock: for each step it
    predicts fixtures kicking off after the simulated time using only data
    before their kickoff, then settles them from the (synthetic) timelines.
    Every resulting row is flagged ``is_demo``.
    """
    from app.ingestion.sync import sync_days
    from app.providers.football.demo import DemoFootballProvider
    from app.scanner.service import run_scan, settle_predictions
    from app.services.settings import set_setting
    from app.workers.jobs import job_backtest

    if get_settings().football_provider != "demo":
        sys.exit("seed-demo only runs with FOOTBALL_PROVIDER=demo")
    with SessionLocal() as db:
        if reset:
            reset_demo(db)
        anchor = datetime.now(UTC).date()
        set_setting(db, "demo.anchor", {"date": anchor.isoformat()}, None)
        db.commit()
        provider = DemoFootballProvider(anchor=anchor)
        days = sorted({datetime.fromisoformat(f.kickoff_at.isoformat()).date()
                       for f in (provider.fixture_with_events(i) for i in provider.all_fixture_ids())})
        stats = sync_days(db, provider, days)
        now = utcnow()
        step = timedelta(hours=12)
        t = datetime.combine((now - timedelta(days=replay_days)).date(), time(0), UTC)
        scans = 0
        while t < now:
            run_scan(db, now=t, notify=False, replay=True)
            scans += 1
            t += step
        db.commit()
        run_scan(db, notify=False)
        settled = settle_predictions(db)
        db.commit()
        bt = job_backtest(db, days=60)
        odds = None
        if get_settings().odds_provider == "demo":
            from app.workers.jobs import job_odds

            odds = job_odds(db)
        return {"odds": odds, "anchor": anchor.isoformat(), "ingest": stats.as_dict() | {"errors": stats.errors[:5]},
                "replay_scans": scans, "settled": settled, "backtest": bt}


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin")
    a.add_argument("--email", required=True)
    a.add_argument("--password")
    s = sub.add_parser("seed-demo")
    s.add_argument("--reset", action="store_true")
    s.add_argument("--replay-days", type=int, default=14)
    sub.add_parser("reset-demo")
    sub.add_parser("bootstrap", help="idempotent first start: admin from BOOTSTRAP_ADMIN_* env + demo data once")
    for job in ("sync", "scan", "settle", "odds", "expire", "notify"):
        sub.add_parser(job)
    sub.add_parser("doctor", help="readiness check: what is live on this deployment and what is not (exit 1 on any FAIL)")
    cu = sub.add_parser("create-user", help="create a verified normal user (for teammates testing a shared deployment)")
    cu.add_argument("--email", required=True)
    cu.add_argument("--password")
    cu.add_argument("--plan", choices=["free", "starter", "pro", "elite"], default="free")
    rn = sub.add_parser("renew", help="reminders + auto-renewal charges + expiry. --as-of simulates a later date (demo payments only)")
    rn.add_argument("--as-of", help="pretend it is this UTC time, e.g. 2026-12-01T09:00 (refused unless PAYMENT_PROVIDER=demo)")
    rn.add_argument("--advance-days", type=float, help="pretend N days have passed, e.g. 30 (refused unless PAYMENT_PROVIDER=demo)")
    lg = sub.add_parser("leagues", help="search the provider's leagues by name to find ids for FOOTBALL_LEAGUE_IDS")
    lg.add_argument("--search", required=True, help="at least 3 characters, e.g. premier")
    pc = sub.add_parser("provider-check", help="cheap read-only check: provider health + one real fixture timeline (run before backfill)")
    pc.add_argument("--date", help="probe one specific date, YYYY-MM-DD")
    pc.add_argument("--league", help="with --season: probe a whole league-season (2 requests)")
    pc.add_argument("--season", type=int, help="season start year, e.g. 2023 for 2023/24")
    bs = sub.add_parser("backfill-season", help="download whole league-seasons (about 20 requests each); resumable")
    bs.add_argument("--league", required=True, help="provider league id, e.g. 39")
    bs.add_argument("--season", type=int, nargs="+", required=True, help="season start year(s), e.g. 2022 2023")
    bt = sub.add_parser("backtest", help="walk-forward evaluation of the baseline on finished matches")
    bt.add_argument("--days", type=int, default=120)
    bt.add_argument("--from", dest="start", help="window start, YYYY-MM-DD (use with --to for historical seasons)")
    bt.add_argument("--to", dest="end", help="window end, YYYY-MM-DD")
    b = sub.add_parser("backfill", help="pull past fixtures + event timelines from the configured provider (resumable)")
    b.add_argument("--days", type=int, default=90)
    b.add_argument("--force", action="store_true", help="re-fetch days that were already synchronised")
    t = sub.add_parser("train", help="train & walk-forward evaluate ML models (promotes only if all gates pass)")
    t.add_argument("--blocks", type=int, default=6)
    t.add_argument("--no-promote", action="store_true")
    oi = sub.add_parser("odds-import", help="import odds from an authorised source: JSON file {\"rows\": [...]}")
    oi.add_argument("file")
    r = sub.add_parser("rollback-model", help="reactivate the Poisson baseline for a market")
    r.add_argument("--market", choices=["MARKET_A", "MARKET_B"], required=True)
    args = parser.parse_args(argv)
    if args.cmd == "create-admin":
        create_admin(args.email, args.password)
    elif args.cmd == "seed-demo":
        print(json.dumps(seed_demo(args.reset, args.replay_days), indent=2, default=str))
    elif args.cmd == "bootstrap":
        print(json.dumps(bootstrap(), indent=2))
    elif args.cmd == "reset-demo":
        with SessionLocal() as db:
            reset_demo(db)
        print("Demo data removed")
    elif args.cmd == "doctor":
        from app.ops.doctor import FAIL, render, run_all

        checks = run_all()
        print(render(checks))
        if any(c.status == FAIL for c in checks):
            sys.exit(1)
    elif args.cmd == "create-user":
        create_user(args.email, args.password, args.plan)
    elif args.cmd == "renew":
        from app.workers.jobs import job_renew

        when = None
        if args.as_of or args.advance_days is not None:
            if get_settings().payment_provider != "demo":
                sys.exit("--as-of/--advance-days are only allowed with PAYMENT_PROVIDER=demo (never with real charges)")
            when = (datetime.fromisoformat(args.as_of).replace(tzinfo=UTC) if args.as_of
                    else utcnow() + timedelta(days=args.advance_days))
            print(f"(simulated clock: {when:%Y-%m-%d %H:%M} UTC)")
        with SessionLocal() as db:
            print(json.dumps(job_renew(db, when), indent=2, default=str))
    elif args.cmd == "leagues":
        from app.providers.football.registry import get_provider

        with SessionLocal() as db:
            provider = get_provider(db)
            try:
                rows = provider.search_leagues(args.search)
            except NotImplementedError as exc:
                sys.exit(str(exc))
        print(f"{'ID':>6}  {'TYPE':8} {'COUNTRY':18} NAME")
        for r in rows:
            print(f"{r['id']!s:>6}  {str(r['type']):8} {str(r['country']):18} {r['name']}")
        print(f"\n{len(rows)} result(s). Put the ids you want in .env, e.g. FOOTBALL_LEAGUE_IDS=39,140")
    elif args.cmd == "provider-check":
        from datetime import date

        from app.ingestion.diagnostics import check_provider, check_season
        from app.providers.football.base import LeagueScopeError
        from app.providers.football.registry import get_provider

        with SessionLocal() as db:
            provider = get_provider(db)
            if args.league and args.season:
                print(json.dumps(check_season(provider, args.league, args.season), indent=2, default=str))
            else:
                from app.ingestion.sync import league_scope

                try:
                    allow = league_scope(provider)
                except LeagueScopeError as exc:
                    sys.exit(str(exc))
                only = date.fromisoformat(args.date) if args.date else None
                print(json.dumps(check_provider(provider, date.today(), allow, only_day=only), indent=2, default=str))
    elif args.cmd == "backfill-season":
        from app.ingestion.sync import sync_league_season
        from app.providers.football.registry import get_provider

        with SessionLocal() as db:
            provider = get_provider(db)
            for season in args.season:
                print(f"Downloading league {args.league}, season {season} ...")

                last = {"n": 0}

                def show(o, last=last):
                    if o["timelines_fetched"] - last["n"] >= 20:
                        last["n"] = o["timelines_fetched"]
                        print(f"  timelines downloaded this run: {o['timelines_fetched']} (of {o['finished']} finished matches)")

                try:
                    out = sync_league_season(db, provider, args.league, season, progress=show)
                except NotImplementedError as exc:
                    sys.exit(str(exc))
                print(json.dumps(out, indent=2, default=str))
                if out["stopped_reason"]:
                    print(f"\nSTOPPED: {out['stopped_reason']}")
                    break
    elif args.cmd == "backtest":
        from datetime import datetime as dt

        from app.workers.jobs import job_backtest

        def to_dt(v):
            return dt.fromisoformat(v).replace(tzinfo=UTC) if v else None

        with SessionLocal() as db:
            print(json.dumps(job_backtest(db, args.days, to_dt(args.start), to_dt(args.end)), indent=2, default=str))
    elif args.cmd == "backfill":
        from app.ingestion.sync import backfill_history
        from app.providers.football.base import LeagueScopeError
        from app.providers.football.registry import get_provider

        with SessionLocal() as db:
            provider = get_provider(db)
            print(f"Backfilling {args.days} days from provider '{provider.name}' ...")
            def show(day, t):
                print(f"  through {day}: {t['fixtures_created']} new, {t['events_replaced']} timelines")

            try:
                out = backfill_history(db, provider, args.days, force=args.force, progress=show)
            except LeagueScopeError as exc:
                sys.exit(str(exc))
            print(json.dumps(out, indent=2, default=str))
    elif args.cmd == "train":
        from app.workers.jobs import job_train

        with SessionLocal() as db:
            print(json.dumps(job_train(db, args.blocks, not args.no_promote), indent=2, default=str))
    elif args.cmd == "odds-import":
        from pathlib import Path

        from app.api.v1.admin import OddsImportIn
        from app.services.odds import import_odds

        payload = OddsImportIn.model_validate_json(Path(args.file).read_text(encoding="utf-8"))
        with SessionLocal() as db:
            result = import_odds(db, [r.model_dump() for r in payload.rows])
            db.commit()
        print(json.dumps(result, indent=2, default=str))
    elif args.cmd == "rollback-model":
        from app.engine.ml.training import rollback_to_baseline

        with SessionLocal() as db:
            mv = rollback_to_baseline(db, args.market)
            db.commit()
            print(f"Active {args.market} model: {mv.name} v{mv.version}")
    else:
        from app.workers.jobs import run_named

        with SessionLocal() as db:
            print(json.dumps(run_named(db, args.cmd), indent=2, default=str))


if __name__ == "__main__":
    main()
