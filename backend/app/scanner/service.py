"""Automated match scanner, prediction persistence and settlement.

Pipeline (run by Celery beat, or manually from the admin dashboard):
  1. pick upcoming fixtures in enabled competitions within the lookahead window
  2. analyse each fixture (leak-free features + both Poisson models)
  3. categorise per market against admin thresholds
  4. insert immutable predictions (new row only when inputs changed)
  5. notify subscribed users about newly qualified matches
Settlement runs separately once fixtures are final.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.logging import get_logger
from app.engine.predictor import analyse_fixture, categorize, confidence_label
from app.engine.settlement import GoalTiming, Market, Result, settle
from app.ingestion.service import Ingestor
from app.models import (
    Competition,
    Fixture,
    MatchEvent,
    ModelVersion,
    Notification,
    Prediction,
    PredictionOutcome,
    SyncRun,
    User,
)
from app.services.entitlements import users_with_feature
from app.services.settings import default_rule_row, get_setting, rule_from_row

log = get_logger(__name__)

BASELINE_VERSION = "1.0.0"
MARKETS = (Market.A.value, Market.B.value)


def ensure_model_versions(db: Session) -> dict[str, ModelVersion]:
    """Make sure an active baseline model version exists for each market."""
    params = get_setting(db, "model.baseline")
    out: dict[str, ModelVersion] = {}
    for market in MARKETS:
        mv = db.scalar(select(ModelVersion).where(ModelVersion.market_code == market, ModelVersion.is_active.is_(True)))
        if mv is None:
            mv = db.scalar(
                select(ModelVersion).where(ModelVersion.market_code == market, ModelVersion.version == BASELINE_VERSION)
            )
        if mv is None:
            mv = ModelVersion(
                market_code=market,
                name="Poisson baseline" + (" (no goal)" if market == Market.A else " (level score)"),
                version=BASELINE_VERSION,
                algorithm="poisson_baseline",
                params=params,
                feature_set_version="fs-1",
                calibration_status="uncalibrated",
                is_active=True,
                notes="Gamma-Poisson smoothed team strengths x competition baseline.",
            )
            db.add(mv)
            db.flush()
        out[market] = mv
    return out


@dataclass
class ScanSummary:
    fixtures_considered: int = 0
    predictions_created: int = 0
    unchanged: int = 0
    skipped_started: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    newly_qualified: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def run_scan(db: Session, now: datetime | None = None, notify: bool = True, replay: bool = False) -> ScanSummary:
    """Scan upcoming fixtures. ``replay`` (demo seeding only) evaluates fixtures
    by kickoff window regardless of their current status, with a simulated
    ``now`` - features are still strictly limited to data before kickoff."""
    now = now or utcnow()
    thresholds = get_setting(db, "scanner.thresholds")
    params = get_setting(db, "model.baseline")
    rule_row = default_rule_row(db)
    models = ensure_model_versions(db)
    horizon = now + timedelta(hours=float(thresholds.get("lookahead_hours", 72)))
    run = SyncRun(job="scanner_replay" if replay else "scanner", provider="engine", status="running", started_at=utcnow())
    db.add(run)
    db.flush()

    summary = ScanSummary()
    fixtures = db.scalars(
        select(Fixture)
        .join(Competition, Competition.id == Fixture.competition_id)
        .where(
            (Fixture.status.notin_(["postponed", "cancelled"])) if replay else (Fixture.status == "scheduled"),
            Fixture.kickoff_at > now,
            Fixture.kickoff_at <= horizon,
            Competition.is_enabled.is_(True),
        )
        .order_by(Fixture.kickoff_at)
    ).all()
    for fx in fixtures:
        summary.fixtures_considered += 1
        analysis = analyse_fixture(db, fx, params, thresholds)
        for market in MARKETS:
            mv = models[market]
            current = db.scalar(
                select(Prediction).where(
                    Prediction.fixture_id == fx.id, Prediction.market_code == market, Prediction.is_current.is_(True)
                )
            )
            if current and current.input_data_version == analysis.input_version and current.model_version_id == mv.id:
                summary.unchanged += 1
                summary.by_category[current.category] = summary.by_category.get(current.category, 0) + 1
                continue
            category, reasons = categorize(analysis, market, thresholds)
            if current is not None:
                current.is_current = False
                current.superseded_at = now
                db.flush()
            pred = Prediction(
                fixture_id=fx.id,
                market_code=market,
                model_version_id=mv.id,
                settlement_rule_id=rule_row.id,
                predicted_at=now,
                kickoff_at=fx.kickoff_at,
                input_data_version=analysis.input_version,
                probability=analysis.probability(market),
                lambda_home=analysis.probs.lambdas.home,
                lambda_away=analysis.probs.lambdas.away,
                components=_components(analysis, market),
                confidence=confidence_label(analysis.uncertainty[market]),
                data_quality=analysis.data_quality,
                sample_home=analysis.home_rates.sample_size,
                sample_away=analysis.away_rates.sample_size,
                category=category,
                category_reasons=reasons,
                is_current=True,
                is_demo=fx.is_demo,
            )
            db.add(pred)
            db.flush()
            summary.predictions_created += 1
            summary.by_category[category] = summary.by_category.get(category, 0) + 1
            if category == "qualified" and (current is None or current.category != "qualified"):
                summary.newly_qualified.append(pred.id)
    if notify and summary.newly_qualified:
        _notify_qualified(db, summary.newly_qualified)
    run.status, run.finished_at, run.stats = "success", utcnow(), summary.as_dict()
    db.flush()
    log.info("scan_complete", **{k: v for k, v in summary.as_dict().items() if k != "newly_qualified"})
    return summary


def _components(analysis, market: str) -> dict:
    lam = analysis.probs.lambdas
    base = {
        "uncertainty_sd": analysis.uncertainty[market],
        "attack_home": round(lam.attack_home, 4),
        "defence_home": round(lam.defence_home, 4),
        "attack_away": round(lam.attack_away, 4),
        "defence_away": round(lam.defence_away, 4),
        "league_home_rate": round(analysis.league.home_rate, 5),
        "league_away_rate": round(analysis.league.away_rate, 5),
        "league_sample": analysis.league.sample_size,
        "feature_set_version": analysis.feature_set_version,
    }
    if market == Market.B:
        base["level_scores"] = {k: round(v, 6) for k, v in analysis.probs.components_b.items()}
    return base


def _notify_qualified(db: Session, prediction_ids: list[int]) -> None:
    preds = db.scalars(select(Prediction).where(Prediction.id.in_(prediction_ids))).all()
    if not preds:
        return
    recipients = users_with_feature(db, "notifications")
    for user in recipients:
        if not (user.notification_prefs or {}).get("scanner_qualified", True):
            continue
        for p in preds:
            fx = p.fixture
            db.add(
                Notification(
                    user_id=user.id,
                    kind="scanner_match",
                    title=f"Qualified: {fx.home_team.name} vs {fx.away_team.name}",
                    body=(
                        f"{'No goal' if p.market_code == Market.A else 'Level score'} at 5' - model estimate "
                        f"{p.probability:.1%} ({p.model_version.calibration_status}). Kick-off "
                        f"{fx.kickoff_at:%Y-%m-%d %H:%M} UTC." + (" [DEMO DATA]" if p.is_demo else "")
                    ),
                    link=f"/matches/{fx.id}",
                )
            )
    db.flush()


def settle_predictions(db: Session) -> dict:
    """Settle (or re-settle after provider corrections) current-or-past predictions."""
    stats = {"settled": 0, "resettled": 0, "pending": 0}
    rule_cache: dict[int, object] = {}
    from app.models import SettlementRule

    preds = db.scalars(
        select(Prediction)
        .join(Fixture, Fixture.id == Prediction.fixture_id)
        .where(Prediction.is_current.is_(True), Fixture.status.notin_(["scheduled", "live"]))
    ).all()
    for p in preds:
        fx = p.fixture
        if p.settlement_rule_id not in rule_cache:
            rule_cache[p.settlement_rule_id] = rule_from_row(db.get(SettlementRule, p.settlement_rule_id))
        rule = rule_cache[p.settlement_rule_id]
        if p.outcome is not None and p.outcome.source_data_version == fx.data_version:
            continue
        events = db.scalars(select(MatchEvent).where(MatchEvent.fixture_id == fx.id)).all()
        goals: list[GoalTiming] = Ingestor.goal_timings(fx, events)
        result, score, note = settle(
            p.market_code, fx.status, goals if fx.events_synced_at else None, rule, fx.timeline_status == "complete"
        )
        if result is Result.PENDING:
            stats["pending"] += 1
            continue
        if p.outcome is None:
            db.add(
                PredictionOutcome(
                    prediction_id=p.id,
                    result=result.value,
                    home_score_at_cutoff=score.home if score else None,
                    away_score_at_cutoff=score.away if score else None,
                    source_data_version=fx.data_version,
                    notes=note,
                )
            )
            stats["settled"] += 1
        else:
            o = p.outcome
            o.result, o.notes, o.source_data_version = result.value, note, fx.data_version
            o.home_score_at_cutoff = score.home if score else None
            o.away_score_at_cutoff = score.away if score else None
            o.revision += 1
            o.settled_at = utcnow()
            stats["resettled"] += 1
    db.flush()
    return stats


def user_ids(users: list[User]) -> list[int]:
    return [u.id for u in users]
