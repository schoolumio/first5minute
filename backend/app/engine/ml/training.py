"""Train, evaluate and register candidate models; promote only when gates pass."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.logging import get_logger
from app.engine.ml.dataset import FEATURES, Dataset, build_dataset
from app.engine.ml.evaluation import evaluate, promotion_decision, select_best
from app.engine.ml.models import IdentityCalibrator, candidate_models, make_calibrator
from app.engine.ml.serving import ModelBundle, clear_cache, save_bundle
from app.engine.ml.tracking import log_training_run
from app.engine.settlement import Market
from app.models import ModelMetric, ModelVersion
from app.services.audit import audit
from app.services.settings import get_setting

log = get_logger(__name__)
METRIC_NAMES = ("brier", "log_loss", "ece", "accuracy", "precision", "recall", "base_rate", "mean_predicted")


def train_market(db: Session, ds_all: Dataset, market: str, n_blocks: int = 6, auto_promote: bool = False) -> dict:
    ds = ds_all.market(market)
    settings = get_settings()
    threshold = get_setting(db, "scanner.thresholds").get(market, {}).get("qualified_min_probability", 0.9)
    result = evaluate(ds, market, n_blocks=n_blocks, threshold=threshold)
    report = result.report
    if report.get("status") != "ok":
        return {"market": market, "registered": False, "report": report}
    variant = select_best(report)
    assert variant is not None
    decision = promotion_decision(report, variant, ds.is_demo, settings.ml_min_oos_sample)

    base_name, _, cal_name = variant.partition("+")
    model = candidate_models(market)[base_name].fit(ds)
    calibrator = IdentityCalibrator()
    if cal_name:
        oof = result.oof_raw[base_name]
        y_test = ds.y[market][result.first_test_index:]
        calibrator = make_calibrator(len(oof)).fit(oof, y_test)
    now = utcnow()
    version = f"ml-{now:%Y%m%d%H%M%S}"
    sel = report["variants"][variant]
    base = report["variants"]["poisson_baseline"]
    if ds.is_demo:
        status = "demo_only"
    elif cal_name and decision["eligible"]:
        status = "calibrated"
    else:
        status = "uncalibrated"
    bundle = ModelBundle(market=market, variant=variant, model=model, calibrator=calibrator, features=list(FEATURES),
                         meta={"trained_at": now.isoformat(), "n_train": len(ds), "n_oos": report["n_oos"], "is_demo": ds.is_demo})
    path = save_bundle(bundle, version)
    params = {"variant": variant, "artifact": str(path), "n_train": len(ds), "n_blocks": n_blocks,
              "calibrator": calibrator.name, "features": len(FEATURES), "k_pooling": getattr(model, "k", None)}
    run_id = log_training_run(
        market, version, {k: v for k, v in params.items() if v is not None},
        {f"oos_{k}": sel[k] for k in ("brier", "log_loss", "ece") if sel.get(k) is not None}
        | {"baseline_log_loss": base["log_loss"], "n_oos": report["n_oos"]},
        {"market": market, "demo": str(ds.is_demo), "eligible": str(decision["eligible"])}, path, report)
    mv = ModelVersion(
        market_code=market, name=f"{variant} ({'no goal' if market == Market.A else 'level score'})", version=version,
        algorithm=variant[:48], params=params, feature_set_version="fs-1", calibration_status=status, is_active=False,
        notes=("Promotion gates: " + ("PASSED" if decision["eligible"] else "NOT passed - " + "; ".join(decision["reasons"]))),
        mlflow_run_id=run_id)
    db.add(mv)
    db.flush()
    window = (ds.kickoff[result.eval_index[0]].astype("datetime64[s]").astype(datetime).replace(tzinfo=UTC),
              ds.kickoff[-1].astype("datetime64[s]").astype(datetime).replace(tzinfo=UTC))
    for name in METRIC_NAMES:
        db.add(ModelMetric(model_version_id=mv.id, evaluation="walk_forward_oos", metric_name=name, value=sel.get(name),
                           sample_size=report["n_oos"], window_start=window[0], window_end=window[1], is_demo=ds.is_demo,
                           details={"variant": variant, "folds": report["folds_log_loss"],
                                    "variants": {k: {m: v[m] for m in ("brier", "log_loss", "ece", "vs_baseline", "vs_climatology")}
                                                 for k, v in report["variants"].items()},
                                    "decision": decision} if name == "log_loss" else {"variant": variant}))
    for name in ("brier", "log_loss", "ece"):
        db.add(ModelMetric(model_version_id=mv.id, evaluation="walk_forward_oos", metric_name=f"baseline_{name}", value=base[name],
                           sample_size=report["n_oos"], window_start=window[0], window_end=window[1], is_demo=ds.is_demo, details={}))
    promoted = False
    if auto_promote and decision["eligible"]:
        activate_model(db, mv.id)
        promoted = True
    audit(db, "model.trained", None, "model_version", mv.id, {"variant": variant, "eligible": decision["eligible"], "promoted": promoted})
    db.flush()
    log.info("model_trained", market=market, variant=variant, oos=report["n_oos"], eligible=decision["eligible"])
    return {"market": market, "registered": True, "model_version_id": mv.id, "version": version, "variant": variant,
            "calibration_status": status, "promoted": promoted, "decision": decision,
            "oos": {k: sel[k] for k in ("sample_size", "brier", "log_loss", "ece")},
            "baseline": {k: base[k] for k in ("brier", "log_loss", "ece")},
            "vs_baseline": sel["vs_baseline"], "is_demo": ds.is_demo, "report": report}


def train_all(db: Session, n_blocks: int = 6, auto_promote: bool = False) -> dict:
    ds = build_dataset(db)
    out = {"dataset": {"rows": len(ds), "is_demo": ds.is_demo, "skipped": ds.skipped}, "markets": {}}
    for market in (Market.A.value, Market.B.value):
        r = train_market(db, ds, market, n_blocks=n_blocks, auto_promote=auto_promote)
        r["report_summary"] = {k: v for k, v in r.get("report", {}).items() if k in ("status", "n_oos", "message", "n_rows")}
        r.pop("report", None)
        out["markets"][market] = r
    return out


def activate_model(db: Session, model_version_id: int) -> ModelVersion:
    """Make one version the single active model of its market (others deactivated, never deleted)."""
    mv = db.get(ModelVersion, model_version_id)
    if mv is None:
        raise ValueError("model version not found")
    if mv.algorithm != "poisson_baseline":
        from app.engine.ml.serving import load_bundle

        load_bundle(mv)  # fails fast if the artifact is missing/corrupt
    db.execute(update(ModelVersion).where(ModelVersion.market_code == mv.market_code, ModelVersion.id != mv.id)
               .values(is_active=False))
    mv.is_active = True
    clear_cache()
    db.flush()
    return mv


def rollback_to_baseline(db: Session, market: str) -> ModelVersion:
    mv = db.scalar(select(ModelVersion).where(ModelVersion.market_code == market, ModelVersion.algorithm == "poisson_baseline")
                   .order_by(ModelVersion.id))
    if mv is None:
        raise ValueError("no baseline model version registered")
    return activate_model(db, mv.id)


__all__ = ["activate_model", "rollback_to_baseline", "train_all", "train_market"]
