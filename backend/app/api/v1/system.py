"""Public system status: is the platform on live data or demo data?"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models import SyncRun

router = APIRouter(tags=["system"])


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # pragma: no cover
        db_ok = False
    last = {}
    for job in ("sync_fixtures", "scanner", "settlement", "odds_sync"):
        run = db.scalar(select(SyncRun).where(SyncRun.job == job).order_by(SyncRun.started_at.desc()).limit(1))
        last[job] = {"status": run.status, "at": (run.finished_at or run.started_at).isoformat()} if run else None
    return {
        "environment": s.environment,
        "data_mode": "demo" if s.demo_mode else "live",
        "football_provider": s.football_provider,
        "odds_provider": s.odds_provider,
        "payments_enabled": s.payment_provider != "none",
        "database": "ok" if db_ok else "error",
        "last_runs": last,
        "demo_notice": (
            "DEMO MODE: all fixtures, teams, results and predictions are synthetic development data. "
            "No live football provider is connected." if s.demo_mode else None
        ),
    }
