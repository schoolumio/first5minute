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

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.logging import get_logger
from app.engine.ml.serving import load_bundle
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
    SavedMatch,
    SyncRun,
)
from app.scanner.eligibility import BLOCK_PREFIX, assess_competitions, eligibility_block
from app.services.email import send_email
from app.services.entitlements import users_with_feature
from app.services.settings import default_rule_row, get_setting, rule_from_row

log = get_logger(__name__)

BASELINE_VERSION = "1.0.0"
MARKETS = (Market.A.value, Market.B.value)


def baseline_version(db: Session, market: str) -> ModelVersion:
    mv = db.scalar(select(ModelVersion).where(ModelVersion.market_code == market, ModelVersion.algorithm == "poisson_baseline")
                   .order_by(ModelVersion.id))
    if mv is None:
        mv = ensure_model_versions(db)[market]
    return mv


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
    if not replay:
        assess_competitions(db, now)
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
            block = eligibility_block(fx.competition)
            was_blocked = bool(current) and any(str(r).startswith(BLOCK_PREFIX) for r in current.category_reasons)
            if (current and current.input_data_version == analysis.input_version and current.model_version_id == mv.id
                    and was_blocked == bool(block)):
                summary.unchanged += 1
                summary.by_category[current.category] = summary.by_category.get(current.category, 0) + 1
                continue
            category, reasons = categorize(analysis, market, thresholds)
            if block:
                category, reasons = "excluded", [block, *reasons]
            used_mv, probability = mv, analysis.probability(market)
            if mv.algorithm != "poisson_baseline":
                try:
                    probability = load_bundle(mv).predict_one(analysis, fx)
                except Exception as exc:  # noqa: BLE001 - never lose a prediction because a model failed
                    log.error("ml_model_failed_falling_back", model_version=mv.id, error=str(exc))
                    used_mv = baseline_version(db, market)
                    reasons = [*reasons, "active ML model unavailable - baseline Poisson used"]
                    same_inputs = current is not None and current.input_data_version == analysis.input_version
                    if same_inputs and current.model_version_id == used_mv.id:
                        summary.unchanged += 1
                        continue
            if current is not None:
                current.is_current = False
                current.superseded_at = now
                db.flush()
            pred = Prediction(
                fixture_id=fx.id,
                market_code=market,
                model_version_id=used_mv.id,
                settlement_rule_id=rule_row.id,
                predicted_at=now,
                kickoff_at=fx.kickoff_at,
                input_data_version=analysis.input_version,
                probability=probability,
                lambda_home=analysis.probs.lambdas.home,
                lambda_away=analysis.probs.lambdas.away,
                components=_components(analysis, market)
                | {"model_variant": used_mv.algorithm, "baseline_probability": round(analysis.probability(market), 5)},
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


def _market_label(code: str) -> str:
    return "No goal" if code == Market.A else "Level score"


def _safe_email(to: str, subject: str, body: str) -> None:
    try:
        send_email(to, subject, body)
    except Exception as exc:  # noqa: BLE001 - a mail failure must never break scanning or settlement
        log.warning("notification_email_failed", error=str(exc))


def _notify_qualified(db: Session, prediction_ids: list[int]) -> None:
    preds = db.scalars(select(Prediction).where(Prediction.id.in_(prediction_ids)).order_by(Prediction.kickoff_at)).all()
    if not preds:
        return
    for user in users_with_feature(db, "notifications"):
        prefs = user.notification_prefs or {}
        if not prefs.get("scanner_qualified", True):
            continue
        lines = []
        for p in preds:
            fx = p.fixture
            text = (f"{_market_label(p.market_code)} at 5' - model estimate {p.probability:.1%} "
                    f"({p.model_version.calibration_status}). Kick-off {fx.kickoff_at:%Y-%m-%d %H:%M} UTC."
                    + (" [DEMO DATA]" if p.is_demo else ""))
            db.add(Notification(user_id=user.id, kind="scanner_match", title=f"Qualified: {fx.home_team.name} vs {fx.away_team.name}",
                                body=text, link=f"/matches/{fx.id}"))
            lines.append(f"- {fx.home_team.name} vs {fx.away_team.name} ({fx.competition.name}): {text}")
        if prefs.get("email"):
            shown = "\n".join(lines[:10]) + (f"\n...and {len(lines) - 10} more" if len(lines) > 10 else "")
            _safe_email(user.email, f"First5Minute: {len(preds)} newly qualified match(es)",
                        f"New matches qualified in the scanner:\n\n{shown}\n\nOpen the scanner: {get_settings().frontend_url}/scanner\n\n"
                        "Estimates are statistical, not guarantees. 18+. Change email alerts in Account > Profile.")
    db.flush()


def _notify_settled(db: Session, settled: list[tuple[Prediction, PredictionOutcome]]) -> None:
    """Tell users who saved a fixture how it settled (Pro+ feature, opt-in via preferences)."""
    if not settled:
        return
    by_fixture: dict[int, list[tuple[Prediction, PredictionOutcome]]] = {}
    for p, o in settled:
        by_fixture.setdefault(p.fixture_id, []).append((p, o))
    saved = db.scalars(select(SavedMatch).where(SavedMatch.fixture_id.in_(list(by_fixture)))).all()
    eligible = {u.id: u for u in users_with_feature(db, "notifications")}
    labels = {"won": "correct", "lost": "incorrect", "void": "void", "unresolved": "unresolved"}
    for sm in saved:
        user = eligible.get(sm.user_id)
        if user is None or not (user.notification_prefs or {}).get("prediction_settled", False):
            continue
        fx = sm.fixture
        parts = [f"{_market_label(p.market_code)}: {labels.get(o.result, o.result)} (estimate {p.probability:.1%})"
                 for p, o in by_fixture[fx.id]]
        cut = next((o for _, o in by_fixture[fx.id] if o.home_score_at_cutoff is not None), None)
        score = f" Score at 5': {cut.home_score_at_cutoff}-{cut.away_score_at_cutoff}." if cut else ""
        body = "; ".join(parts) + "." + score
        db.add(Notification(user_id=user.id, kind="prediction_settled", title=f"Settled: {fx.home_team.name} vs {fx.away_team.name}",
                            body=body, link=f"/matches/{fx.id}"))
        if (user.notification_prefs or {}).get("email"):
            _safe_email(user.email, f"First5Minute: {fx.home_team.name} vs {fx.away_team.name} settled", body)
    db.flush()


def settle_predictions(db: Session) -> dict:
    """Settle (or re-settle after provider corrections) current-or-past predictions."""
    stats = {"settled": 0, "resettled": 0, "pending": 0}
    newly: list[tuple[Prediction, PredictionOutcome]] = []
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
            outcome = PredictionOutcome(
                prediction_id=p.id,
                result=result.value,
                home_score_at_cutoff=score.home if score else None,
                away_score_at_cutoff=score.away if score else None,
                source_data_version=fx.data_version,
                notes=note,
            )
            db.add(outcome)
            newly.append((p, outcome))
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
    _notify_settled(db, newly)
    return stats
