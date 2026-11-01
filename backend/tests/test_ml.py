"""Phase 3: advanced models, walk-forward evaluation integrity, calibration, promotion and serving."""

from datetime import timedelta

import numpy as np
import pytest
from scipy.special import expit, logit
from sqlalchemy import select

from app.core.database import utcnow
from app.engine import metrics
from app.engine.ml.dataset import FEATURES, HIER_FIELDS, Dataset, build_dataset
from app.engine.ml.evaluation import (
    EMBARGO,
    block_edges,
    evaluate,
    paired_bootstrap,
    promotion_decision,
    select_best,
)
from app.engine.ml.models import (
    FI,
    HI,
    BaselineModel,
    GBMModel,
    HierPoissonModel,
    IdentityCalibrator,
    IsotonicCalibrator,
    LogisticModel,
    MarketModel,
    PlattCalibrator,
    candidate_models,
    make_calibrator,
)
from app.engine.settlement import Rule
from app.ingestion.service import Ingestor
from app.models import Fixture, ModelMetric, ModelVersion, Prediction
from tests import factories as f
from tests.conftest import login

M = "MARKET_A"


def synthetic(n=900, signal=1.5, seed=3, demo=False) -> Dataset:
    """Dataset whose outcome depends on a hidden feature the Poisson baseline does not see."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, len(FEATURES)))
    base_logit = rng.normal(1.8, 0.3, size=n)
    X[:, FI["logit_base_a"]] = base_logit
    X[:, FI["logit_base_b"]] = base_logit + 0.05
    hidden = rng.normal(size=n)
    X[:, FI["home_clean_pct"]] = hidden
    p = expit(base_logit + signal * hidden)
    y = (rng.random(n) < p).astype(int)
    H = np.abs(rng.normal(1, 0.5, size=(n, len(HIER_FIELDS)))) + 0.01
    H[:, HI["lg_home"]], H[:, HI["lg_away"]] = 0.075, 0.055
    kick = np.datetime64("2026-01-01T12:00") + (np.arange(n) * np.timedelta64(7, "h"))
    ds = Dataset(kick.astype("datetime64[ns]"), np.arange(n), X, H, rng.poisson(0.07, n).astype(float), rng.poisson(0.05, n).astype(float),
                 is_demo=demo)
    ds.y = {M: y, "MARKET_B": y}
    ds.mask = {M: np.ones(n, bool), "MARKET_B": np.ones(n, bool)}
    return ds


def test_models_learn_real_signal_out_of_sample():
    ds = synthetic().market(M)
    rep = evaluate(ds, M, n_blocks=6).report
    assert rep["status"] == "ok" and rep["n_oos"] > 400
    v = rep["variants"]
    # The hidden feature is invisible to the baseline; logistic and the residual booster must exploit it.
    assert v["logistic"]["log_loss"] < v["poisson_baseline"]["log_loss"] - 0.03
    assert v["logistic"]["vs_baseline"]["ci_high"] < 0          # significantly better
    assert v["lightgbm_residual"]["log_loss"] < v["poisson_baseline"]["log_loss"]
    assert select_best(rep) in {"logistic", "logistic+platt", "ensemble", "ensemble+platt", "lightgbm_residual", "lightgbm_residual+platt"}


def test_pure_noise_is_never_promoted():
    ds = synthetic(signal=0.0, seed=11).market(M)
    rep = evaluate(ds, M).report
    best = select_best(rep)
    d = promotion_decision(rep, best, is_demo=False, min_oos=300)
    assert not d["eligible"]
    assert any("significantly" in r for r in d["reasons"])


def test_promotion_gates_demo_and_sample_size():
    ds = synthetic(n=1200)
    rep = evaluate(ds.market(M), M).report
    best = select_best(rep)
    assert promotion_decision(rep, best, is_demo=False, min_oos=300)["eligible"]
    d_demo = promotion_decision(rep, best, is_demo=True, min_oos=300)
    assert not d_demo["eligible"] and "demo" in d_demo["reasons"][0]
    assert any("out-of-sample" in r for r in promotion_decision(rep, best, is_demo=False, min_oos=10_000)["reasons"])


def test_walk_forward_never_trains_on_the_future():
    ds = synthetic(n=700).market(M)
    seen: list[tuple[np.datetime64, int]] = []

    class Spy(MarketModel):
        name = "spy"

        def fit(self, d):
            self.max_train = d.kickoff.max() if len(d) else None
            seen.append((self.max_train, len(d)))
            return self

        def predict(self, X, H):
            return np.full(len(X), 0.8)

    def factory(market):
        return {"poisson_baseline": BaselineModel(market), "climatology": candidate_models(market)["climatology"], "spy": Spy(market)}

    res = evaluate(ds, M, n_blocks=5, model_factory=factory)
    edges = [e for e in block_edges(ds.kickoff, 5) if e >= 80]
    assert res.report["status"] == "ok" and len(seen) >= 3
    for (max_train, n_train), start in zip(seen, edges, strict=False):
        assert max_train < ds.kickoff[start] - EMBARGO        # embargo respected
        assert n_train <= start                                # only strictly earlier rows
    # first test row is never part of any training set that predicted it
    assert res.first_test_index >= 80


def test_calibration_only_uses_earlier_blocks():
    ds = synthetic(n=900).market(M)
    res = evaluate(ds, M, n_blocks=6)
    assert any(k.endswith("+platt") or k.endswith("+isotonic") for k in res.preds)
    # every calibrated variant is evaluated on the same rows as the raw variants
    lens = {len(v) for v in res.preds.values()}
    assert lens == {len(res.eval_index)}
    assert res.eval_index[0] > res.first_test_index        # first test block reserved for calibration fit


def test_platt_and_isotonic_reduce_calibration_error():
    rng = np.random.default_rng(1)
    true_p = rng.uniform(0.6, 0.98, 4000)
    y = (rng.random(4000) < true_p).astype(int)
    over = np.clip(true_p + 0.08, 0, 0.995)                 # systematically over-confident
    before = metrics.expected_calibration_error(over.tolist(), y.tolist())
    for cal in (PlattCalibrator(), IsotonicCalibrator()):
        fit = cal.fit(over[:2000], y[:2000])
        after = metrics.expected_calibration_error(fit.predict(over[2000:]).tolist(), y[2000:].tolist())
        assert after < before / 2
    assert isinstance(make_calibrator(30), IdentityCalibrator)
    assert isinstance(make_calibrator(300), PlattCalibrator) and isinstance(make_calibrator(5000), IsotonicCalibrator)


def test_paired_bootstrap_direction():
    rng = np.random.default_rng(0)
    base = rng.uniform(0.3, 0.6, 500)
    better = base - 0.05 + rng.normal(0, 0.01, 500)
    r = paired_bootstrap(better, base)
    assert r["mean_diff"] < 0 and r["ci_high"] < 0 and r["p_better"] > 0.99
    same = paired_bootstrap(base, base + rng.normal(0, 0.2, 500))
    assert same["ci_low"] < 0 < same["ci_high"]


def test_hier_model_pools_hard_when_teams_are_alike_and_softly_when_they_differ():
    rng = np.random.default_rng(2)
    n = 1500
    H = np.zeros((n, len(HIER_FIELDS)))
    H[:, HI["lg_home"]], H[:, HI["lg_away"]] = 0.08, 0.06
    n_hist = np.full(n, 15.0)

    def build(strength_sd):
        att_h = np.exp(rng.normal(0, strength_sd, n))
        att_a = np.exp(rng.normal(0, strength_sd, n))
        gh, ga = rng.poisson(0.07 * att_h), rng.poisson(0.07 * att_a)
        D = H.copy()
        D[:, HI["h_n"]], D[:, HI["a_n"]] = n_hist, n_hist
        D[:, HI["h_for"]], D[:, HI["a_for"]] = rng.poisson(0.07 * att_h * n_hist), rng.poisson(0.07 * att_a * n_hist)
        D[:, HI["h_against"]], D[:, HI["a_against"]] = rng.poisson(0.07 * n_hist), rng.poisson(0.07 * n_hist)
        ds = Dataset(np.arange(n).astype("datetime64[h]").astype("datetime64[ns]"), np.arange(n), np.zeros((n, len(FEATURES))), D,
                     gh.astype(float), ga.astype(float))
        ds.y = {M: np.zeros(n, int)}
        return ds

    k_alike = HierPoissonModel(M).fit(build(0.0)).k
    k_diverse = HierPoissonModel(M).fit(build(0.8)).k
    assert k_alike > k_diverse                                # stronger shrinkage when no real team differences exist


def test_gbm_close_to_baseline_with_tiny_samples():
    ds = synthetic(n=40).market(M)
    g = GBMModel(M).fit(ds)
    assert g.gbm is None                                       # too little data -> falls back to the baseline exactly
    assert np.allclose(g.predict(ds.X, ds.H), BaselineModel(M).predict(ds.X, ds.H))
    assert LogisticModel(M).fit(ds).predict(ds.X, ds.H).shape == (40,)


def test_insufficient_data_is_reported_not_faked():
    rep = evaluate(synthetic(n=60).market(M), M).report
    assert rep["status"] == "insufficient_data" and "walk-forward needs" in rep["message"]


# ------------------------------------------------------------------ database integration
def _league(db, now):
    ing = Ingestor(db, "mock", False, Rule())
    for nf in f.season_history(now - timedelta(days=60), n_teams=6, rounds=14):
        ing.ingest_fixture(nf)
    ing.ingest_fixture(f.upcoming("up1", 1, 2, now + timedelta(hours=20)))
    db.commit()


def test_dataset_features_are_leak_free(db):
    now = utcnow()
    _league(db, now)
    before = build_dataset(db)
    assert len(before) > 10 and set(before.y) == {"MARKET_A", "MARKET_B"}
    ing = Ingestor(db, "mock", False, Rule())
    for i in range(6):                                          # later matches must not change earlier features
        ing.ingest_fixture(f.fixture(f"late{i}", 1 + i % 5, 2 + i % 4 + (i % 4 == 0), now - timedelta(hours=10 - i), [f.goal(2, "mt1")]))
    db.commit()
    after = build_dataset(db, end=now - timedelta(days=1))
    assert len(after) <= len(before)
    idx = {fid: i for i, fid in enumerate(before.fixture_ids)}
    for j, fid in enumerate(after.fixture_ids):
        assert np.allclose(after.X[j], before.X[idx[fid]])
        assert np.allclose(after.H[j], before.H[idx[fid]])


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "model_dir", str(tmp_path))
    from app.engine.ml.serving import clear_cache

    clear_cache()
    return tmp_path


def test_train_register_activate_and_serve(db, model_dir):
    from app.engine.ml.training import activate_model, rollback_to_baseline, train_market
    from app.scanner.service import ensure_model_versions, run_scan

    now = utcnow()
    _league(db, now)
    ensure_model_versions(db)
    out = train_market(db, synthetic(n=1200), M, auto_promote=True)
    db.commit()
    assert out["registered"] and out["decision"]["eligible"] and out["promoted"]
    assert out["calibration_status"] in ("calibrated", "uncalibrated")
    mv = db.get(ModelVersion, out["model_version_id"])
    assert mv.is_active and (model_dir / M / f"{mv.version}.joblib").exists()
    assert db.scalar(select(ModelVersion.id).where(ModelVersion.market_code == M, ModelVersion.algorithm == "poisson_baseline",
                                                    ModelVersion.is_active.is_(True))) is None
    metric_names = {m.metric_name for m in db.scalars(select(ModelMetric).where(ModelMetric.model_version_id == mv.id))}
    assert {"brier", "log_loss", "ece", "baseline_log_loss"} <= metric_names

    run_scan(db, now=now, notify=False)
    db.commit()
    p = db.scalar(select(Prediction).join(Fixture).where(Fixture.provider_id == "up1", Prediction.market_code == M, Prediction.is_current))
    assert p.model_version_id == mv.id and p.components["model_variant"] == out["variant"]
    assert 0 < p.probability < 1 and "baseline_probability" in p.components

    # Roll back: a *new* prediction is written (old rows kept), and the baseline is current again.
    rollback_to_baseline(db, M)
    db.commit()
    run_scan(db, now=now + timedelta(minutes=1), notify=False)
    db.commit()
    rows = db.scalars(select(Prediction).join(Fixture).where(Fixture.provider_id == "up1", Prediction.market_code == M)
                      .order_by(Prediction.id)).all()
    assert len(rows) == 2 and not rows[0].is_current and rows[1].is_current
    assert rows[1].model_version.algorithm == "poisson_baseline"
    activate_model(db, mv.id)                                   # and forward again without a constraint violation
    db.commit()
    run_scan(db, now=now + timedelta(minutes=2), notify=False)
    db.commit()
    assert db.scalar(select(Prediction.model_version_id).join(Fixture).where(
        Fixture.provider_id == "up1", Prediction.market_code == M, Prediction.is_current)) == mv.id


def test_missing_artifact_falls_back_to_baseline(db, model_dir):
    from app.engine.ml.training import train_market
    from app.scanner.service import ensure_model_versions, run_scan

    now = utcnow()
    _league(db, now)
    ensure_model_versions(db)
    out = train_market(db, synthetic(n=1200), M, auto_promote=True)
    db.commit()
    mv = db.get(ModelVersion, out["model_version_id"])
    (model_dir / M / f"{mv.version}.joblib").unlink()
    from app.engine.ml.serving import clear_cache

    clear_cache()
    run_scan(db, now=now, notify=False)
    db.commit()
    p = db.scalar(select(Prediction).join(Fixture).where(Fixture.provider_id == "up1", Prediction.market_code == M, Prediction.is_current))
    assert p.model_version.algorithm == "poisson_baseline"
    assert any("baseline Poisson used" in r for r in p.category_reasons)


def test_demo_trained_models_are_registered_but_not_promoted(db, model_dir):
    from app.engine.ml.training import train_market

    out = train_market(db, synthetic(n=1200, demo=True), M, auto_promote=True)
    db.commit()
    mv = db.get(ModelVersion, out["model_version_id"])
    assert out["registered"] and not out["promoted"] and not mv.is_active
    assert mv.calibration_status == "demo_only" and "NOT passed" in mv.notes


def test_admin_activation_requires_ack_for_ineligible_models(client, db, user_factory, model_dir):
    from app.engine.ml.training import train_market
    from app.scanner.service import ensure_model_versions

    ensure_model_versions(db)
    out = train_market(db, synthetic(n=1200, demo=True), M, auto_promote=False)
    db.commit()
    user_factory(email="mlboss@example.com", role="admin")
    user_factory(email="mlplain@example.com", plan="elite")
    mid = out["model_version_id"]
    login(client, "mlplain@example.com")
    assert client.post(f"/api/v1/admin/models/{mid}/activate", json={}).status_code == 403
    client.cookies.clear()
    login(client, "mlboss@example.com")
    r = client.post(f"/api/v1/admin/models/{mid}/activate", json={})
    assert r.status_code == 409 and "promotion gates" in r.text
    ok = client.post(f"/api/v1/admin/models/{mid}/activate", json={"acknowledge_not_eligible": True})
    assert ok.status_code == 200 and ok.json()["overridden_gates"] is True
    assert client.post(f"/api/v1/admin/models/{M}/rollback").json()["market"] == M
    models = client.get("/api/v1/admin/model-performance").json()["models"]
    assert any(m["id"] == mid and not m["is_active"] for m in models)


def test_logit_helper_roundtrip():
    assert float(expit(logit(0.9))) == pytest.approx(0.9)


def test_mlflow_tracking_logs_a_run_when_configured(tmp_path, monkeypatch):
    mlflow = pytest.importorskip("mlflow")
    from app.core.config import get_settings
    from app.engine.ml.tracking import log_training_run

    monkeypatch.setenv("MLFLOW_DISABLE_AGENT_HINT", "1")
    monkeypatch.setattr(get_settings(), "mlflow_tracking_uri", f"sqlite:///{tmp_path}/mlflow.db")
    run_id = log_training_run("MARKET_A", "ml-test", {"variant": "logistic"}, {"oos_log_loss": 0.4}, {"demo": "True"},
                              None, {"status": "ok"})
    assert run_id
    runs = mlflow.search_runs(experiment_names=[get_settings().mlflow_experiment])
    assert float(runs.loc[runs.run_id == run_id, "metrics.oos_log_loss"].iloc[0]) == pytest.approx(0.4)


def test_tracking_is_a_noop_and_never_raises_when_unconfigured_or_broken(monkeypatch):
    from app.core.config import get_settings
    from app.engine.ml.tracking import log_training_run

    assert log_training_run("MARKET_A", "v", {}, {}, {}) is None
    monkeypatch.setattr(get_settings(), "mlflow_tracking_uri", "http://127.0.0.1:1/nope")
    assert log_training_run("MARKET_A", "v", {}, {"a": 1.0}, {}) is None
