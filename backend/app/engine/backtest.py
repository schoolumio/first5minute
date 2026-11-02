"""Walk-forward backtesting of the baseline models.

For every finished fixture in the evaluation window (in kickoff order) the
model is evaluated *as of that fixture's kickoff*, using only earlier data -
the same leak-free code path as live predictions. Results are grouped into
monthly walk-forward folds and summarised with Brier score, log loss,
calibration, precision/recall. ROI is simulated only with real odds
snapshots captured before kickoff; when none exist ROI is reported as
unavailable rather than estimated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.engine import metrics
from app.engine.predictor import analyse_fixture
from app.engine.settlement import Market, Result, settle
from app.ingestion.service import Ingestor
from app.models import BettingMarket, Bookmaker, Fixture, MatchEvent, ModelMetric, ModelVersion, OddsSnapshot
from app.services.settings import default_rule_row, get_setting, rule_from_row


def _best_pre_kickoff_odds(db: Session, fixture: Fixture, market_code: str, default_rule_id: int | None = None) -> float | None:
    """Best price a bettor could have taken at kick-off: each bookmaker's LAST available pre-kickoff price, best across
    bookmakers. Demo odds, inactive bookmakers and bookmakers settling by a different rule are never used."""
    rows = db.execute(
        select(OddsSnapshot.bookmaker_id, OddsSnapshot.selection, OddsSnapshot.decimal_odds, OddsSnapshot.is_available)
        .join(BettingMarket, BettingMarket.id == OddsSnapshot.market_id)
        .join(Bookmaker, Bookmaker.id == OddsSnapshot.bookmaker_id)
        .where(OddsSnapshot.fixture_id == fixture.id, BettingMarket.code == market_code, OddsSnapshot.captured_at < fixture.kickoff_at,
               OddsSnapshot.is_demo.is_(False), Bookmaker.is_active.is_(True), Bookmaker.is_demo.is_(False),
               or_(Bookmaker.settlement_rule_id.is_(None), Bookmaker.settlement_rule_id == default_rule_id))
        .order_by(OddsSnapshot.captured_at.desc(), OddsSnapshot.id.desc())).all()
    last: dict[tuple[int, str], tuple[float, bool]] = {}
    for bm_id, sel, odds, ok in rows:
        last.setdefault((bm_id, sel), (float(odds), ok))
    live = [o for o, ok in last.values() if ok]
    return max(live) if live else None


def walk_forward(
    db: Session,
    start: datetime,
    end: datetime,
    min_team_sample: int = 5,
    persist_for: dict[str, ModelVersion] | None = None,
) -> dict:
    params = get_setting(db, "model.baseline")
    thresholds = get_setting(db, "scanner.thresholds")
    rule_row = default_rule_row(db)
    rule = rule_from_row(rule_row)
    fixtures = db.scalars(
        select(Fixture)
        .where(Fixture.status == "finished", Fixture.kickoff_at >= start, Fixture.kickoff_at < end)
        .order_by(Fixture.kickoff_at)
    ).all()
    data: dict[str, list[tuple[str, float, int, float | None]]] = {m.value: [] for m in Market}
    skipped = defaultdict(int)
    any_demo = False
    for fx in fixtures:
        analysis = analyse_fixture(db, fx, params, thresholds)
        if analysis.min_sample < min_team_sample:
            skipped["insufficient_history"] += 1
            continue
        events = db.scalars(select(MatchEvent).where(MatchEvent.fixture_id == fx.id)).all()
        goals = Ingestor.goal_timings(fx, events)
        any_demo = any_demo or fx.is_demo
        fold = fx.kickoff_at.strftime("%Y-%m")
        for market in Market:
            result, _, _ = settle(market, fx.status, goals, rule, fx.timeline_status == "complete")
            if result not in (Result.WON, Result.LOST):
                skipped[f"unsettled_{market.value}"] += 1
                continue
            odds = _best_pre_kickoff_odds(db, fx, market.value, rule_row.id)
            data[market.value].append((fold, analysis.probability(market), int(result is Result.WON), odds))

    report: dict = {"window": [start.isoformat(), end.isoformat()], "skipped": dict(skipped), "is_demo": any_demo}
    for market, rows in data.items():
        probs = [r[1] for r in rows]
        ys = [r[2] for r in rows]
        threshold = thresholds.get(market, {}).get("qualified_min_probability", 0.9)
        summary = metrics.summarize(probs, ys, threshold)
        folds = defaultdict(list)
        for fold, p, y, _ in rows:
            folds[fold].append((p, y))
        summary["folds"] = [
            {
                "fold": f,
                "n": len(v),
                "brier": metrics.brier_score([p for p, _ in v], [y for _, y in v]),
                "log_loss": metrics.log_loss([p for p, _ in v], [y for _, y in v]),
            }
            for f, v in sorted(folds.items())
        ]
        priced = [(o, bool(y)) for _, p, y, o in rows if o is not None and p >= threshold]
        summary["roi"] = (
            metrics.roi_simulation(priced) if priced else {"bets": 0, "roi": None, "note": "no real odds recorded"}
        )
        report[market] = summary
        if persist_for and market in persist_for and probs:
            mv = persist_for[market]
            for name in ("brier", "log_loss", "ece", "accuracy", "precision", "recall", "base_rate", "mean_predicted"):
                db.add(
                    ModelMetric(
                        model_version_id=mv.id,
                        evaluation="walk_forward",
                        metric_name=name,
                        value=summary[name],
                        sample_size=summary["sample_size"],
                        window_start=start,
                        window_end=end,
                        details={"calibration": summary["calibration"]} if name == "ece" else {},
                        is_demo=any_demo,
                    )
                )
            db.flush()
    return report
