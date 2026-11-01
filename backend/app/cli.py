"""Operational CLI.

  python -m app.cli create-admin --email admin@example.com --password '...'
  python -m app.cli seed-demo [--reset] [--replay-days 14]
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


def reset_demo(db) -> None:
    """Remove all demo-flagged data (never touches live provider data)."""
    db.execute(text("SET LOCAL projectfive.allow_prediction_delete = 'on'"))
    db.execute(text("DELETE FROM predictions WHERE is_demo"))
    db.execute(text("DELETE FROM notifications WHERE body LIKE '%[DEMO DATA]%'"))
    for table in ("saved_matches", "bet_tracking", "odds_snapshots"):
        db.execute(text(f"DELETE FROM {table} WHERE fixture_id IN (SELECT id FROM fixtures WHERE is_demo)"))  # noqa: S608 - constant table names
    db.execute(text("DELETE FROM team_match_stats WHERE fixture_id IN (SELECT id FROM fixtures WHERE is_demo)"))
    db.execute(text("DELETE FROM fixtures WHERE is_demo"))
    db.execute(text("DELETE FROM seasons WHERE competition_id IN (SELECT id FROM competitions WHERE is_demo)"))
    db.execute(text("DELETE FROM competitions WHERE is_demo"))
    db.execute(text("DELETE FROM teams WHERE is_demo"))
    db.execute(text("DELETE FROM model_metrics WHERE is_demo"))
    db.execute(text("DELETE FROM provider_payloads WHERE provider = 'demo'"))
    db.commit()


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
        return {"anchor": anchor.isoformat(), "ingest": stats.as_dict() | {"errors": stats.errors[:5]},
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
    for job in ("sync", "scan", "settle", "backtest", "expire"):
        sub.add_parser(job)
    args = parser.parse_args(argv)
    if args.cmd == "create-admin":
        create_admin(args.email, args.password)
    elif args.cmd == "seed-demo":
        print(json.dumps(seed_demo(args.reset, args.replay_days), indent=2, default=str))
    elif args.cmd == "reset-demo":
        with SessionLocal() as db:
            reset_demo(db)
        print("Demo data removed")
    else:
        from app.workers.jobs import run_named

        with SessionLocal() as db:
            print(json.dumps(run_named(db, args.cmd), indent=2, default=str))


if __name__ == "__main__":
    main()
