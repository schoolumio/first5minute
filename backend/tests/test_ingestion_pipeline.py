"""Integration: ingestion -> features -> predictions -> settlement, with MOCK provider data."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.database import utcnow
from app.engine.backtest import walk_forward
from app.engine.settlement import Rule
from app.ingestion.service import Ingestor
from app.models import Fixture, Prediction, PredictionOutcome, ProviderPayload, TeamMatchStats
from app.scanner.service import ensure_model_versions, run_scan, settle_predictions
from tests import factories as f


def ingestor(db):
    return Ingestor(db, "mock", False, Rule())


def test_ingest_derives_early_stats_and_is_idempotent(db):
    ing = ingestor(db)
    ko = utcnow() - timedelta(days=3)
    nf = f.fixture("x1", 1, 2, ko, [f.goal(2, "mt1"), f.goal(4, "mt1", detail="own_goal"), f.goal(50, "mt2")])
    fx = ing.ingest_fixture(nf)
    db.commit()
    assert fx.timeline_status == "complete" and (fx.home_score_ft, fx.away_score_ft) == (1, 2)
    home = db.scalar(select(TeamMatchStats).where(TeamMatchStats.fixture_id == fx.id, TeamMatchStats.is_home))
    assert (home.early_goals_for, home.early_goals_against, home.first_goal_minute, home.reliable) == (1, 1, 2, True)
    # Re-ingesting identical data creates nothing new and does not bump the version.
    ing.ingest_fixture(nf)
    db.commit()
    assert db.scalar(select(Fixture.data_version).where(Fixture.id == fx.id)) == 1
    assert db.scalar(select(text("count(*)")).select_from(Fixture)) == 1
    assert db.scalar(select(text("count(*)")).select_from(ProviderPayload)) == 2  # fixture + events payloads


def test_inconsistent_timeline_marked_unreliable(db):
    ing = ingestor(db)
    nf = f.fixture("x2", 1, 2, utcnow() - timedelta(days=2), [f.goal(10, "mt1")], score=(2, 0))
    fx = ing.ingest_fixture(nf)
    db.commit()
    assert fx.timeline_status == "inconsistent"
    assert all(not s.reliable for s in db.scalars(select(TeamMatchStats).where(TeamMatchStats.fixture_id == fx.id)))


def test_rejects_invalid_fixture(db):
    with pytest.raises(ValueError):
        ingestor(db).ingest_fixture(f.fixture("bad", 1, 1, utcnow(), []))


def _seed_league(db, now):
    ing = ingestor(db)
    for nf in f.season_history(now - timedelta(days=60), n_teams=6, rounds=14):
        ing.ingest_fixture(nf)
    ing.ingest_fixture(f.upcoming("up1", 1, 2, now + timedelta(hours=20)))
    ing.ingest_fixture(f.upcoming("up2", 7, 8, now + timedelta(hours=30)))  # teams with no history
    db.commit()


def test_scan_creates_predictions_for_both_markets(db):
    now = utcnow()
    _seed_league(db, now)
    summary = run_scan(db, now=now)
    db.commit()
    assert summary.fixtures_considered == 2 and summary.predictions_created == 4
    preds = db.scalars(select(Prediction).order_by(Prediction.id)).all()
    up1 = [p for p in preds if p.fixture.provider_id == "up1"]
    up2 = [p for p in preds if p.fixture.provider_id == "up2"]
    assert {p.market_code for p in up1} == {"MARKET_A", "MARKET_B"}
    a = next(p for p in up1 if p.market_code == "MARKET_A")
    b = next(p for p in up1 if p.market_code == "MARKET_B")
    assert 0 < a.probability < b.probability < 1  # level score includes 0-0
    assert a.sample_home >= 10 and a.data_quality in ("medium", "high", "low")
    assert a.predicted_at < a.kickoff_at and a.model_version.version == "1.0.0"
    assert "level_scores" in b.components
    # Fixtures without event history are never assigned a qualifying prediction.
    assert all(p.category == "excluded" and p.data_quality == "insufficient" for p in up2)
    # Re-running without new data does not create duplicates.
    again = run_scan(db, now=now)
    assert again.predictions_created == 0 and again.unchanged == 4


def test_no_leakage_future_results_do_not_change_inputs(db):
    now = utcnow()
    _seed_league(db, now)
    run_scan(db, now=now)
    db.commit()
    before = db.scalar(select(Prediction).where(Prediction.market_code == "MARKET_A", Prediction.is_current)
                       .join(Fixture).where(Fixture.provider_id == "up1"))
    # A match involving team 1 that kicks off AFTER up1 must not affect up1's features.
    ingestor(db).ingest_fixture(f.fixture("later", 1, 3, now + timedelta(days=3), [f.goal(1, "mt1")]))
    db.commit()
    run_scan(db, now=now)
    db.commit()
    after = db.scalar(select(Prediction).where(Prediction.market_code == "MARKET_A", Prediction.is_current)
                      .join(Fixture).where(Fixture.provider_id == "up1"))
    assert before.id == after.id and before.input_data_version == after.input_data_version


def test_new_pre_kickoff_data_supersedes_without_overwriting(db):
    now = utcnow()
    _seed_league(db, now)
    run_scan(db, now=now)
    db.commit()
    old = db.scalar(select(Prediction).join(Fixture).where(Fixture.provider_id == "up1", Prediction.market_code == "MARKET_A"))
    old_prob = old.probability
    ingestor(db).ingest_fixture(f.fixture("mid", 1, 4, now - timedelta(hours=2), [f.goal(1, "mt1"), f.goal(2, "mt4")]))
    db.commit()
    run_scan(db, now=now)
    db.commit()
    rows = db.scalars(select(Prediction).join(Fixture).where(Fixture.provider_id == "up1", Prediction.market_code == "MARKET_A")
                      .order_by(Prediction.id)).all()
    assert len(rows) == 2 and not rows[0].is_current and rows[1].is_current
    assert rows[0].probability == old_prob and rows[1].probability < old_prob


def test_predictions_are_immutable_in_database(db):
    now = utcnow()
    _seed_league(db, now)
    run_scan(db, now=now)
    db.commit()
    pid = db.scalar(select(Prediction.id).where(Prediction.is_current).limit(1))
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE predictions SET probability = 0.99 WHERE id = :i"), {"i": pid})
    db.rollback()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("DELETE FROM predictions WHERE id = :i"), {"i": pid})
    db.rollback()
    # Superseding (flag change only) is allowed.
    db.execute(text("UPDATE predictions SET is_current = false, superseded_at = now() WHERE id = :i"), {"i": pid})
    db.rollback()


def test_prediction_after_kickoff_rejected(db):
    now = utcnow()
    _seed_league(db, now)
    models = ensure_model_versions(db)
    fx = db.scalar(select(Fixture).where(Fixture.provider_id == "up1"))
    db.add(Prediction(fixture_id=fx.id, market_code="MARKET_A", model_version_id=models["MARKET_A"].id, settlement_rule_id=1,
                      predicted_at=fx.kickoff_at + timedelta(minutes=1), kickoff_at=fx.kickoff_at, input_data_version="x",
                      probability=0.9, confidence="low", data_quality="low", sample_home=1, sample_away=1,
                      category="excluded", is_current=False))
    with pytest.raises(IntegrityError, match="pre_kickoff"):
        db.flush()


def test_settlement_and_provider_correction(db):
    now = utcnow()
    _seed_league(db, now)
    run_scan(db, now=now)
    db.commit()
    # The match is played: no goal in the first five minutes.
    ing = ingestor(db)
    played = f.fixture("up1", 1, 2, now + timedelta(hours=20), [f.goal(30, "mt1")])
    ing.ingest_fixture(played)
    db.commit()
    stats = settle_predictions(db)
    db.commit()
    assert stats["settled"] == 2
    outs = {o.prediction.market_code: o for o in db.scalars(select(PredictionOutcome))}
    assert outs["MARKET_A"].result == "won" and outs["MARKET_B"].result == "won"
    # Provider corrects the goal time to minute 4 -> re-settled as lost, revision recorded.
    corrected = f.fixture("up1", 1, 2, now + timedelta(hours=20), [f.goal(4, "mt1")])
    ing.ingest_fixture(corrected)
    db.commit()
    stats = settle_predictions(db)
    db.commit()
    assert stats["resettled"] == 2
    db.expire_all()
    outs = {o.prediction.market_code: o for o in db.scalars(select(PredictionOutcome))}
    assert outs["MARKET_A"].result == "lost" and outs["MARKET_A"].revision == 2
    assert (outs["MARKET_A"].home_score_at_cutoff, outs["MARKET_A"].away_score_at_cutoff) == (1, 0)


def test_walk_forward_backtest_reports_metrics_without_odds(db):
    now = utcnow()
    _seed_league(db, now)
    report = walk_forward(db, now - timedelta(days=61), now)
    a = report["MARKET_A"]
    assert a["sample_size"] > 0 and 0 <= a["brier"] <= 1 and a["log_loss"] > 0
    assert a["roi"]["roi"] is None and "no real odds" in a["roi"]["note"]
    assert report["skipped"].get("insufficient_history", 0) > 0  # early-season matches skipped
