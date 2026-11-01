"""Pipeline jobs shared by Celery tasks, the admin 'run job' endpoint and the CLI."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.engine.backtest import walk_forward
from app.ingestion.sync import refresh_pending_results, sync_window
from app.models import SyncRun
from app.providers.football.registry import get_provider
from app.scanner.service import ensure_model_versions, run_scan, settle_predictions
from app.services.billing import expire_subscriptions


def job_sync(db: Session, past_days: int = 2, future_days: int = 3) -> dict:
    provider = get_provider(db)
    stats = sync_window(db, provider, past_days, future_days)
    pending = refresh_pending_results(db, provider)
    return {"window": stats.as_dict(), "refreshed": pending.as_dict()}


def job_scan(db: Session) -> dict:
    summary = run_scan(db)
    db.commit()
    return summary.as_dict()


def job_settle(db: Session) -> dict:
    run = SyncRun(job="settlement", provider="engine", status="running")
    db.add(run)
    stats = settle_predictions(db)
    run.status, run.finished_at, run.stats = "success", utcnow(), stats
    db.commit()
    return stats


def job_backtest(db: Session, days: int = 120) -> dict:
    models = ensure_model_versions(db)
    end = utcnow()
    report = walk_forward(db, end - timedelta(days=days), end, persist_for=models)
    db.commit()
    return {m: {k: report[m][k] for k in ("sample_size", "brier", "log_loss", "ece", "base_rate", "mean_predicted")}
            for m in ("MARKET_A", "MARKET_B")} | {"is_demo": report["is_demo"], "skipped": report["skipped"]}


def job_train(db: Session, n_blocks: int = 6, auto_promote: bool = True) -> dict:
    """Train + walk-forward evaluate candidates. Promotion only if every statistical gate passes."""
    from app.engine.ml.training import train_all

    out = train_all(db, n_blocks=n_blocks, auto_promote=auto_promote)
    db.commit()
    return out


def job_expire(db: Session) -> dict:
    n = expire_subscriptions(db)
    db.commit()
    return {"expired": n}


JOBS = {"sync": job_sync, "scan": job_scan, "settle": job_settle, "backtest": job_backtest, "train": job_train, "expire": job_expire}


def run_named(db: Session, name: str) -> dict:
    return JOBS[name](db)
