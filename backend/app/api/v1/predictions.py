"""Prediction history and model performance."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, get_current_user, page_response
from app.core.database import get_db
from app.engine import metrics
from app.models import Fixture, ModelMetric, ModelVersion, Prediction, PredictionOutcome, User
from app.schemas.common import prediction_out
from app.services.entitlements import entitlements
from app.services.settings import get_setting

router = APIRouter(prefix="/predictions", tags=["predictions"])


def _filtered(market: str | None, competition_id: int | None, date_from: date | None, date_to: date | None,
              outcome: str | None, category: str | None, include_superseded: bool):
    q = select(Prediction).join(Fixture, Fixture.id == Prediction.fixture_id).outerjoin(
        PredictionOutcome, PredictionOutcome.prediction_id == Prediction.id)
    if not include_superseded:
        q = q.where(Prediction.is_current.is_(True))
    if market:
        q = q.where(Prediction.market_code == market)
    if competition_id:
        q = q.where(Fixture.competition_id == competition_id)
    if date_from:
        q = q.where(Prediction.kickoff_at >= datetime.combine(date_from, time(0), UTC))
    if date_to:
        q = q.where(Prediction.kickoff_at < datetime.combine(date_to, time(0), UTC) + timedelta(days=1))
    if outcome == "pending":
        q = q.where(PredictionOutcome.id.is_(None))
    elif outcome:
        q = q.where(PredictionOutcome.result == outcome)
    if category:
        q = q.where(Prediction.category == category)
    return q


@router.get("")
def list_predictions(
    p: Pagination = Depends(),
    market: str | None = Query(default=None, pattern="^MARKET_[AB]$"),
    competition_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    outcome: str | None = Query(default=None, pattern="^(won|lost|void|unresolved|pending)$"),
    category: str | None = Query(default=None, pattern="^(qualified|watchlist|below_threshold|excluded)$"),
    include_superseded: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not entitlements(db, user)["features"].get("historical_analysis"):
        # Free plan: last 7 days of history only.
        floor = (datetime.now(UTC) - timedelta(days=7)).date()
        date_from = max(date_from, floor) if date_from else floor
    q = _filtered(market, competition_id, date_from, date_to, outcome, category, include_superseded)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Prediction.kickoff_at.desc(), Prediction.id.desc()).offset(p.offset).limit(p.page_size)).all()
    return page_response([prediction_out(r) for r in rows], total, p)


def _performance(db: Session, market: str | None, category: str | None, since: datetime | None) -> dict:
    q = (select(Prediction, PredictionOutcome).join(PredictionOutcome, PredictionOutcome.prediction_id == Prediction.id)
         .where(Prediction.is_current.is_(True), PredictionOutcome.result.in_(["won", "lost"])))
    if market:
        q = q.where(Prediction.market_code == market)
    if category:
        q = q.where(Prediction.category == category)
    if since:
        q = q.where(Prediction.kickoff_at >= since)
    rows = db.execute(q).all()
    probs = [p.probability for p, _ in rows]
    ys = [1 if o.result == "won" else 0 for _, o in rows]
    thresholds = get_setting(db, "scanner.thresholds")
    thr = thresholds.get(market or "MARKET_A", {}).get("qualified_min_probability", 0.9)
    s = metrics.summarize(probs, ys, thr)
    s["hit_rate"] = (sum(ys) / len(ys)) if ys else None
    s["is_demo"] = any(p.is_demo for p, _ in rows)
    voids = db.scalar(select(func.count()).select_from(
        select(PredictionOutcome.id).join(Prediction, Prediction.id == PredictionOutcome.prediction_id)
        .where(Prediction.is_current.is_(True), PredictionOutcome.result.in_(["void", "unresolved"]),
               *( [Prediction.market_code == market] if market else [])).subquery())) or 0
    s["void_or_unresolved"] = voids
    return s


@router.get("/performance")
def performance(
    market: str | None = Query(default=None, pattern="^MARKET_[AB]$"),
    days: int | None = Query(default=None, ge=1, le=3650),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    markets = [market] if market else ["MARKET_A", "MARKET_B"]
    out: dict = {"markets": {}}
    detailed = bool(entitlements(db, user)["features"].get("performance_analytics"))
    for m in markets:
        perf = {"all": _performance(db, m, None, since), "qualified": _performance(db, m, "qualified", since)}
        if not detailed:
            for v in perf.values():
                v.pop("calibration", None)
        out["markets"][m] = perf
    models = db.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))).all()
    out["models"] = [{"id": mv.id, "market": mv.market_code, "name": mv.name, "version": mv.version,
                      "calibration_status": mv.calibration_status} for mv in models]
    if detailed:
        wf = db.scalars(select(ModelMetric).where(ModelMetric.evaluation == "walk_forward")
                        .order_by(ModelMetric.created_at.desc()).limit(64)).all()
        out["walk_forward"] = [{"model_version_id": m.model_version_id, "metric": m.metric_name, "value": m.value,
                                "sample_size": m.sample_size, "is_demo": m.is_demo,
                                "window": [m.window_start.isoformat() if m.window_start else None,
                                           m.window_end.isoformat() if m.window_end else None],
                                "details": m.details} for m in wf]
    out["detailed"] = detailed
    out["disclaimer"] = ("Model estimates are uncalibrated statistical outputs. Past performance does not guarantee "
                         "future results. Small samples are highly uncertain.")
    return out


@router.get("/performance/trend")
def performance_trend(
    market: str = Query(pattern="^MARKET_[AB]$"),
    days: int = Query(default=90, ge=7, le=730),
    bucket: str = Query(default="week", pattern="^(day|week|month)$"),
    category: str | None = Query(default=None, pattern="^(qualified|watchlist|below_threshold)$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Observed hit rate vs mean estimated probability per time bucket (settled won/lost predictions only)."""
    capped = False
    if not entitlements(db, user)["features"].get("performance_analytics"):
        if days > 30:
            days, capped = 30, True
    since = datetime.now(UTC) - timedelta(days=days)
    q = (select(Prediction, PredictionOutcome).join(PredictionOutcome, PredictionOutcome.prediction_id == Prediction.id)
         .where(Prediction.is_current.is_(True), Prediction.market_code == market, Prediction.kickoff_at >= since,
                PredictionOutcome.result.in_(["won", "lost"])))
    if category:
        q = q.where(Prediction.category == category)
    groups: dict[str, list[tuple[float, int]]] = {}
    demo = False
    for p, o in db.execute(q):
        d = p.kickoff_at.astimezone(UTC).date()
        if bucket == "week":
            key = (d - timedelta(days=d.weekday())).isoformat()
        elif bucket == "month":
            key = d.replace(day=1).isoformat()
        else:
            key = d.isoformat()
        groups.setdefault(key, []).append((p.probability, 1 if o.result == "won" else 0))
        demo = demo or p.is_demo
    points = []
    for key in sorted(groups):
        rows = groups[key]
        n = len(rows)
        points.append({
            "period": key, "n": n, "hit_rate": sum(y for _, y in rows) / n, "mean_predicted": sum(pr for pr, _ in rows) / n,
            "brier": metrics.brier_score([pr for pr, _ in rows], [y for _, y in rows]),
        })
    return {"market": market, "bucket": bucket, "days": days, "capped_by_plan": capped, "points": points, "is_demo": demo,
            "note": "Buckets with few predictions are noisy; judge trends by the sample size n, not the line alone."}


@router.get("/{prediction_id}")
def get_prediction(prediction_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    p = db.get(Prediction, prediction_id)
    if p is None:
        raise HTTPException(404, "Prediction not found")
    return prediction_out(p)
