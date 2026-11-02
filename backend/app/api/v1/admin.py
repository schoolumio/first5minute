"""Administrator endpoints. Every route requires the admin role; mutations are audited."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Pagination, client_ip, page_response, require_admin
from app.core.config import get_settings
from app.core.database import get_db, utcnow
from app.models import (
    AuditLog,
    Bookmaker,
    Competition,
    DataProviderLog,
    Fixture,
    ModelMetric,
    ModelVersion,
    Plan,
    Prediction,
    PredictionOutcome,
    Role,
    SettlementRule,
    Subscription,
    SyncRun,
    User,
)
from app.providers.football.registry import provider_status
from app.schemas.common import competition_out, fixture_out, user_out
from app.services.audit import audit
from app.services.entitlements import entitlements
from app.services.settings import get_setting, set_setting

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    now = utcnow()
    count = lambda q: db.scalar(q) or 0  # noqa: E731
    return {
        "users": count(select(func.count(User.id))),
        "verified_users": count(select(func.count(User.id)).where(User.email_verified_at.isnot(None))),
        "active_subscriptions": count(select(func.count(Subscription.id)).where(Subscription.status == "active")),
        "competitions": count(select(func.count(Competition.id))),
        "fixtures": count(select(func.count(Fixture.id))),
        "upcoming_fixtures": count(select(func.count(Fixture.id)).where(Fixture.kickoff_at > now)),
        "predictions": count(select(func.count(Prediction.id))),
        "settled_predictions": count(select(func.count(PredictionOutcome.id))),
        "provider_errors_24h": count(select(func.count(DataProviderLog.id)).where(
            DataProviderLog.status != "success", DataProviderLog.created_at > now - timedelta(hours=24))),
        "missing_timelines": count(select(func.count(Fixture.id)).where(
            Fixture.status == "finished", Fixture.timeline_status != "complete")),
        "football_provider": get_settings().football_provider,
        "demo_mode": get_settings().demo_mode,
    }


# --- users -------------------------------------------------------------------
class UserUpdateIn(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|user)$")
    is_active: bool | None = None
    plan_code: str | None = Field(default=None, pattern="^(free|starter|pro|elite)$")
    plan_days: int = Field(default=30, ge=1, le=366)


@router.get("/users")
def list_users(p: Pagination = Depends(), q: str | None = None, db: Session = Depends(get_db)) -> dict:
    query = select(User)
    if q:
        query = query.where(User.email.ilike(f"%{q}%") | User.full_name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(User.created_at.desc()).offset(p.offset).limit(p.page_size)).all()
    return page_response([{**user_out(u, entitlements(db, u)), "is_active": u.is_active} for u in rows], total, p)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdateIn, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.role == "user" or body.is_active is False):
        raise HTTPException(400, "You cannot demote or deactivate your own account")
    changes = body.model_dump(exclude_none=True)
    if body.role:
        role = db.scalar(select(Role).where(Role.name == body.role))
        assert role is not None
        u.role_id = role.id
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.plan_code:
        now = utcnow()
        for s in db.scalars(select(Subscription).where(Subscription.user_id == u.id,
                                                       Subscription.status.in_(["active", "cancelled"]))):
            s.status, s.current_period_end = "expired", now
        if body.plan_code != "free":
            plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
            assert plan is not None
            db.add(Subscription(user_id=u.id, plan_id=plan.id, status="active", current_period_start=now,
                                current_period_end=now + timedelta(days=body.plan_days), payment_provider="admin_grant"))
    audit(db, "admin.user_updated", admin.id, "user", u.id, changes, client_ip(request))
    db.commit()
    db.refresh(u)
    return {**user_out(u, entitlements(db, u)), "is_active": u.is_active}


# --- plans ---------------------------------------------------------------------
class PlanUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    price_minor: int | None = Field(default=None, ge=0, le=1_000_000_000)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    features: dict | None = None
    is_active: bool | None = None


@router.get("/plans")
def admin_plans(db: Session = Depends(get_db)) -> list[dict]:
    from app.api.v1.subscriptions import plan_out

    return [plan_out(p) for p in db.scalars(select(Plan).order_by(Plan.rank)).all()]


@router.patch("/plans/{code}")
def update_plan(code: str, body: PlanUpdateIn, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)) -> dict:
    from app.api.v1.subscriptions import plan_out

    plan = db.scalar(select(Plan).where(Plan.code == code))
    if plan is None:
        raise HTTPException(404, "Plan not found")
    before = plan_out(plan)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(plan, k, v.upper() if k == "currency" else v)
    audit(db, "admin.plan_updated", admin.id, "plan", code, {"before": before, "changes": body.model_dump(exclude_none=True)},
          client_ip(request))
    db.commit()
    return plan_out(plan)


# --- competitions --------------------------------------------------------------
class CompetitionUpdateIn(BaseModel):
    is_enabled: bool | None = None
    eligibility_mode: str | None = Field(default=None, pattern="^(auto|force_on|force_off)$")


@router.get("/competitions")
def admin_competitions(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Competition, func.count(Fixture.id),
               func.count(Fixture.id).filter(Fixture.status == "finished"),
               func.count(Fixture.id).filter(Fixture.status == "finished", Fixture.timeline_status == "complete"))
        .outerjoin(Fixture, Fixture.competition_id == Competition.id).group_by(Competition.id).order_by(Competition.name)
    ).all()
    return [{**competition_out(c), "fixtures": n, "finished": fin,
             "timeline_coverage": round(ok / fin, 4) if fin else None} for c, n, fin, ok in rows]


@router.post("/competitions/assess")
def assess_now(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    from app.scanner.eligibility import assess_competitions

    result = assess_competitions(db)
    audit(db, "admin.competitions_assessed", admin.id, "competition", None, {"count": len(result)}, client_ip(request))
    db.commit()
    return {"assessed": len(result), "ineligible": sum(1 for r in result if r["status"] == "ineligible")}


@router.patch("/competitions/{competition_id}")
def update_competition(competition_id: int, body: CompetitionUpdateIn, request: Request,
                       admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    c = db.get(Competition, competition_id)
    if c is None:
        raise HTTPException(404, "Competition not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(c, k, v)
    audit(db, "admin.competition_updated", admin.id, "competition", c.id, body.model_dump(exclude_none=True), client_ip(request))
    db.commit()
    return competition_out(c)


# --- providers & sync ----------------------------------------------------------
@router.get("/providers")
def providers(db: Session = Depends(get_db)) -> dict:
    since = utcnow() - timedelta(hours=24)
    health = db.execute(
        select(DataProviderLog.provider, DataProviderLog.status, func.count(), func.avg(DataProviderLog.latency_ms))
        .where(DataProviderLog.created_at > since).group_by(DataProviderLog.provider, DataProviderLog.status)
    ).all()
    stats: dict[str, dict] = {}
    for prov, st, n, lat in health:
        d = stats.setdefault(prov, {"success": 0, "error": 0, "rate_limited": 0, "avg_latency_ms": None})
        d[st] = n
        if st == "success":
            d["avg_latency_ms"] = round(float(lat or 0), 1)
    runs = db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(20)).all()
    return {
        "football": provider_status(),
        "odds_provider": get_settings().odds_provider,
        "payment_provider": get_settings().payment_provider,
        "health_24h": stats,
        "recent_runs": [{"id": r.id, "job": r.job, "provider": r.provider, "status": r.status,
                         "started_at": r.started_at.isoformat(),
                         "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                         "stats": r.stats, "error": r.error} for r in runs],
    }


@router.get("/integration-errors")
def integration_errors(p: Pagination = Depends(), db: Session = Depends(get_db)) -> dict:
    q = select(DataProviderLog).where(DataProviderLog.status != "success")
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(DataProviderLog.created_at.desc()).offset(p.offset).limit(p.page_size)).all()
    return page_response([{"id": r.id, "provider": r.provider, "operation": r.operation, "status": r.status,
                           "http_status": r.http_status, "error": r.error, "created_at": r.created_at.isoformat()}
                          for r in rows], total, p)


@router.get("/missing-events")
def missing_events(p: Pagination = Depends(), db: Session = Depends(get_db)) -> dict:
    q = select(Fixture).where(Fixture.status == "finished", Fixture.timeline_status != "complete")
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(Fixture.kickoff_at.desc()).offset(p.offset).limit(p.page_size)).all()
    return page_response([fixture_out(f) for f in rows], total, p)


class JobIn(BaseModel):
    job: str = Field(pattern="^(sync|scan|settle|backtest|train)$")


@router.post("/jobs")
def run_job(body: JobIn, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """Run a pipeline job synchronously (small datasets) - Celery runs them on schedule."""
    from app.workers import jobs

    result = jobs.run_named(db, body.job)
    audit(db, "admin.job_run", admin.id, "job", body.job, {"result": _jsonable(result)}, client_ip(request))
    db.commit()
    return {"job": body.job, "result": _jsonable(result)}


def _jsonable(x):
    import json

    return json.loads(json.dumps(x, default=str))


# --- models --------------------------------------------------------------------
@router.get("/model-performance")
def model_performance(db: Session = Depends(get_db)) -> dict:
    from app.api.v1.predictions import _performance

    versions = db.scalars(select(ModelVersion).order_by(ModelVersion.market_code, ModelVersion.created_at.desc())).all()
    out = []
    for mv in versions:
        metrics = db.scalars(select(ModelMetric).where(ModelMetric.model_version_id == mv.id)
                             .order_by(ModelMetric.created_at.desc()).limit(32)).all()
        live = db.scalar(select(func.count(Prediction.id)).where(Prediction.model_version_id == mv.id)) or 0
        out.append({
            "id": mv.id, "market": mv.market_code, "name": mv.name, "version": mv.version, "algorithm": mv.algorithm,
            "is_active": mv.is_active, "calibration_status": mv.calibration_status, "params": mv.params,
            "notes": mv.notes, "mlflow_run_id": mv.mlflow_run_id, "created_at": mv.created_at.isoformat(),
            "predictions": live,
            "walk_forward": [{"metric": m.metric_name, "value": m.value, "sample_size": m.sample_size,
                              "is_demo": m.is_demo, "created_at": m.created_at.isoformat(), "details": m.details} for m in metrics],
        })
    return {"models": out, "live": {m: _performance(db, m, None, None) for m in ("MARKET_A", "MARKET_B")}}


class ActivateIn(BaseModel):
    acknowledge_not_eligible: bool = False


@router.post("/models/{model_version_id}/activate")
def activate_model_endpoint(model_version_id: int, body: ActivateIn, request: Request, admin: User = Depends(require_admin),
                            db: Session = Depends(get_db)) -> dict:
    """Manual promotion. Models that failed the statistical gates need an explicit acknowledgement."""
    from app.engine.ml.training import activate_model

    mv = db.get(ModelVersion, model_version_id)
    if mv is None:
        raise HTTPException(404, "Model version not found")
    failed_gates = (mv.notes or "").find("NOT passed") >= 0
    if failed_gates and not body.acknowledge_not_eligible:
        raise HTTPException(409, {"message": "This model did not pass the promotion gates. Set acknowledge_not_eligible to override.",
                                  "notes": mv.notes})
    try:
        activate_model(db, mv.id)
    except FileNotFoundError as exc:
        raise HTTPException(422, f"Model artifact unavailable: {exc}") from exc
    audit(db, "admin.model_activated", admin.id, "model_version", mv.id,
          {"market": mv.market_code, "version": mv.version, "override": failed_gates}, client_ip(request))
    db.commit()
    return {"active": mv.version, "market": mv.market_code, "overridden_gates": failed_gates}


@router.post("/models/{market}/rollback")
def rollback_model_endpoint(market: str, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    from app.engine.ml.training import rollback_to_baseline

    if market not in ("MARKET_A", "MARKET_B"):
        raise HTTPException(404, "Unknown market")
    mv = rollback_to_baseline(db, market)
    audit(db, "admin.model_rollback", admin.id, "model_version", mv.id, {"market": market}, client_ip(request))
    db.commit()
    return {"active": mv.version, "market": market}


# --- bookmakers ----------------------------------------------------------------
class BookmakerIn(BaseModel):
    code: str = Field(pattern="^[a-z0-9_-]{2,48}$")
    name: str = Field(max_length=120)
    website_url: HttpUrl | None = None
    deep_link_template: str | None = Field(default=None, max_length=500, pattern="^https://")
    countries: list[str] = Field(default_factory=list)
    is_active: bool = True


class BookmakerUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    website_url: HttpUrl | None = None
    deep_link_template: str | None = Field(default=None, max_length=500, pattern="^https://")
    countries: list[str] | None = None
    is_active: bool | None = None


def _bm_out(b: Bookmaker) -> dict:
    return {"id": b.id, "code": b.code, "name": b.name, "website_url": b.website_url,
            "deep_link_template": b.deep_link_template, "countries": b.countries, "is_active": b.is_active,
            "supports_execution_api": b.supports_execution_api}


@router.get("/bookmakers")
def list_bookmakers(db: Session = Depends(get_db)) -> list[dict]:
    return [_bm_out(b) for b in db.scalars(select(Bookmaker).order_by(Bookmaker.name)).all()]


@router.post("/bookmakers", status_code=201)
def create_bookmaker(body: BookmakerIn, request: Request, admin: User = Depends(require_admin),
                     db: Session = Depends(get_db)) -> dict:
    if db.scalar(select(Bookmaker.id).where(Bookmaker.code == body.code)):
        raise HTTPException(409, "Bookmaker code already exists")
    data = body.model_dump()
    data["website_url"] = str(body.website_url) if body.website_url else None
    b = Bookmaker(**data)
    db.add(b)
    db.flush()
    audit(db, "admin.bookmaker_created", admin.id, "bookmaker", b.id, {"code": b.code}, client_ip(request))
    db.commit()
    return _bm_out(b)


@router.patch("/bookmakers/{bookmaker_id}")
def update_bookmaker(bookmaker_id: int, body: BookmakerUpdateIn, request: Request, admin: User = Depends(require_admin),
                     db: Session = Depends(get_db)) -> dict:
    b = db.get(Bookmaker, bookmaker_id)
    if b is None:
        raise HTTPException(404, "Bookmaker not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(b, k, str(v) if k == "website_url" else v)
    audit(db, "admin.bookmaker_updated", admin.id, "bookmaker", b.id, body.model_dump(exclude_none=True, mode="json"),
          client_ip(request))
    db.commit()
    return _bm_out(b)


# --- settings ------------------------------------------------------------------
class ThresholdMarket(BaseModel):
    qualified_min_probability: float = Field(ge=0.5, le=0.999)
    watchlist_min_probability: float = Field(ge=0.5, le=0.999)


class EligibilityTier(BaseModel):
    min_finished: int = Field(ge=1, le=100000)
    min_coverage: float = Field(ge=0, le=1)


class EligibilityIn(BaseModel):
    lookback_days: int = Field(ge=30, le=1825)
    min_finished: int = Field(ge=1, le=100000)
    min_coverage: float = Field(ge=0, le=1)
    high: EligibilityTier
    medium: EligibilityTier


class ThresholdsIn(BaseModel):
    MARKET_A: ThresholdMarket
    MARKET_B: ThresholdMarket
    qualified_min_team_sample: int = Field(ge=1, le=100)
    watchlist_min_team_sample: int = Field(ge=1, le=100)
    qualified_min_data_quality: str = Field(pattern="^(low|medium|high)$")
    lookahead_hours: int = Field(ge=6, le=336)


class ModelParamsIn(BaseModel):
    prior_strength: float = Field(ge=0, le=100)
    max_history: int = Field(ge=5, le=100)
    half_life_matches: float = Field(ge=1, le=100)
    home_weight: float = Field(ge=0, le=1)
    competition_min_sample: int = Field(ge=0, le=1000)


class FlagsIn(BaseModel):
    registrations_open: bool
    maintenance_mode: bool


SETTINGS_SCHEMAS = {
    "scanner.thresholds": ThresholdsIn,
    "scanner.eligibility": EligibilityIn,
    "model.baseline": ModelParamsIn,
    "platform.flags": FlagsIn,
}


@router.get("/settings")
def get_settings_all(db: Session = Depends(get_db)) -> dict:
    rules = db.scalars(select(SettlementRule).order_by(SettlementRule.id)).all()
    return {
        **{k: get_setting(db, k) for k in SETTINGS_SCHEMAS},
        "settlement_rules": [{"id": r.id, "code": r.code, "description": r.description, "cutoff_seconds": r.cutoff_seconds,
                              "minute_convention": r.minute_convention, "count_own_goals": r.count_own_goals,
                              "void_if_abandoned_before_cutoff": r.void_if_abandoned_before_cutoff,
                              "is_default": r.is_default} for r in rules],
    }


@router.put("/settings/{key}")
def put_setting(key: str, body: dict, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    schema = SETTINGS_SCHEMAS.get(key)
    if schema is None:
        raise HTTPException(404, "Unknown setting")
    value = schema.model_validate(body).model_dump()
    if key == "scanner.thresholds":
        for m in ("MARKET_A", "MARKET_B"):
            if value[m]["watchlist_min_probability"] > value[m]["qualified_min_probability"]:
                raise HTTPException(422, f"{m}: watchlist threshold must not exceed qualified threshold")
    before = get_setting(db, key)
    set_setting(db, key, value, admin.id)
    audit(db, "admin.setting_updated", admin.id, "setting", key, {"before": before, "after": value}, client_ip(request))
    db.commit()
    return value


class DefaultRuleIn(BaseModel):
    rule_id: int


@router.put("/settlement-rules/default")
def set_default_rule(body: DefaultRuleIn, request: Request, admin: User = Depends(require_admin),
                     db: Session = Depends(get_db)) -> dict:
    rule = db.get(SettlementRule, body.rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    for r in db.scalars(select(SettlementRule)):
        r.is_default = r.id == rule.id
    audit(db, "admin.default_rule_changed", admin.id, "settlement_rule", rule.id, {"code": rule.code}, client_ip(request))
    db.commit()
    return {"default": rule.code}


# --- audit ---------------------------------------------------------------------
@router.get("/audit-logs")
def audit_logs(p: Pagination = Depends(), action: str | None = Query(default=None, max_length=64),
               db: Session = Depends(get_db)) -> dict:
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(AuditLog.created_at.desc()).offset(p.offset).limit(p.page_size)).all()
    return page_response([{"id": a.id, "actor_user_id": a.actor_user_id, "action": a.action, "entity_type": a.entity_type,
                           "entity_id": a.entity_id, "details": a.details, "ip_address": a.ip_address,
                           "created_at": a.created_at.isoformat()} for a in rows], total, p)
