"""Walk-forward (expanding-window, out-of-fold) evaluation of candidate models.

Rows are sorted by kickoff and cut into contiguous time blocks. For each test
block the models are fitted only on rows that finished *before* the block
started (3h embargo = match length, so in-play matches never leak in), then
predict the block. Calibrators are fitted only on out-of-fold predictions of
*earlier* test blocks. Everything reported is therefore out-of-sample.

Skill is reported against two references - the Phase-2 Poisson baseline and a
"base rate only" model - with a paired bootstrap on per-match log loss, so
"better" is a statement with a confidence interval, not a point estimate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.engine import metrics
from app.engine.ml.dataset import Dataset
from app.engine.ml.models import (
    IdentityCalibrator,
    MarketModel,
    candidate_models,
    make_calibrator,
)

EMBARGO = np.timedelta64(3, "h")
REFERENCES = ("poisson_baseline", "climatology")


def _row_logloss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def block_edges(kickoff: np.ndarray, n_blocks: int) -> list[int]:
    """Start indices of ``n_blocks`` blocks, snapped to calendar-day boundaries."""
    n = len(kickoff)
    days = kickoff.astype("datetime64[D]")
    edges = [0]
    for b in range(1, n_blocks):
        i = int(round(b * n / n_blocks))
        while 0 < i < n and days[i] == days[i - 1]:
            i += 1
        if i < n and i > edges[-1]:
            edges.append(i)
    return edges


def paired_bootstrap(loss_a: np.ndarray, loss_b: np.ndarray, n_boot: int = 2000, seed: int = 5) -> dict:
    """Mean(loss_a - loss_b) with a 95% percentile CI (negative = a is better)."""
    d = loss_a - loss_b
    if len(d) < 2:
        return {"mean_diff": float(d.mean()) if len(d) else None, "ci_low": None, "ci_high": None, "p_better": None}
    rng = np.random.default_rng(seed)
    means = rng.choice(d, size=(n_boot, len(d)), replace=True).mean(axis=1)
    return {"mean_diff": float(d.mean()), "ci_low": float(np.percentile(means, 2.5)),
            "ci_high": float(np.percentile(means, 97.5)), "p_better": float((means < 0).mean())}


@dataclass
class EvalResult:
    market: str
    n_rows: int
    n_oos: int
    first_test_index: int
    eval_index: np.ndarray                           # row indices of the common evaluation set
    preds: dict[str, np.ndarray] = field(default_factory=dict)       # variant name -> p on eval rows (aligned)
    oof_raw: dict[str, np.ndarray] = field(default_factory=dict)     # model -> raw OOF p on all test rows
    test_index: np.ndarray = field(default_factory=lambda: np.array([], int))
    y_eval: np.ndarray = field(default_factory=lambda: np.array([], int))
    report: dict = field(default_factory=dict)


def evaluate(ds: Dataset, market: str, n_blocks: int = 6, min_train: int = 80, threshold: float = 0.9,
             model_factory=candidate_models) -> EvalResult:
    """``ds`` must already be restricted to the market (``Dataset.market``)."""
    n = len(ds)
    y = ds.y[market]
    edges = block_edges(ds.kickoff, n_blocks)
    # first block whose predecessors hold at least min_train rows
    starts = [e for e in edges if e >= min_train]
    res = EvalResult(market=market, n_rows=n, n_oos=0, first_test_index=-1, eval_index=np.array([], int))
    if len(starts) < 3:  # need >=2 test blocks (one to calibrate on, one to evaluate)
        res.report = {"market": market, "status": "insufficient_data", "n_rows": n,
                      "message": f"{n} usable matches - walk-forward needs at least ~{min_train} for training plus two test blocks."}
        return res
    bounds = starts + [n]
    names = list(model_factory(market))
    raw = {k: np.full(n, np.nan) for k in names}
    test_blocks: list[tuple[int, int]] = list(zip(bounds[:-1], bounds[1:], strict=True))
    for lo, hi in test_blocks:
        train_mask = ds.kickoff < (ds.kickoff[lo] - EMBARGO)
        train_mask[lo:] = False
        train = _subset(ds, train_mask)
        models = model_factory(market)
        for name, m in models.items():
            m.fit(train)
            raw[name][lo:hi] = m.predict(ds.X[lo:hi], ds.H[lo:hi])
    first = test_blocks[0][0]
    test_idx = np.arange(first, n)
    eval_start = test_blocks[1][0]                    # first block that has an earlier block to calibrate on
    eval_idx = np.arange(eval_start, n)
    preds: dict[str, np.ndarray] = {}
    for name in names:
        preds[name] = raw[name][eval_idx]
        if name in ("climatology",):
            continue
        cal_p = np.full(len(eval_idx), np.nan)
        cal_name = "none"
        for lo, hi in test_blocks[1:]:
            fit_mask = (ds.kickoff < (ds.kickoff[lo] - EMBARGO)) & (np.arange(n) >= first)
            cal = make_calibrator(int(fit_mask.sum())).fit(raw[name][fit_mask], y[fit_mask])
            cal_name = cal.name
            cal_p[lo - eval_start:hi - eval_start] = cal.predict(raw[name][lo:hi])
        if cal_name != "none":
            preds[f"{name}+{cal_name}"] = cal_p
    y_eval = y[eval_idx]
    thr = threshold
    report: dict = {"market": market, "status": "ok", "n_rows": n, "n_oos": int(len(eval_idx)), "n_blocks": len(test_blocks),
                    "embargo_hours": 3, "threshold": thr, "base_rate_eval": float(y_eval.mean()), "variants": {}}
    base_loss = _row_logloss(preds["poisson_baseline"], y_eval)
    clim_loss = _row_logloss(preds["climatology"], y_eval)
    for name, p in preds.items():
        s = metrics.summarize(p.tolist(), y_eval.tolist(), thr)
        loss = _row_logloss(p, y_eval)
        s["vs_baseline"] = paired_bootstrap(loss, base_loss) if name != "poisson_baseline" else None
        s["vs_climatology"] = paired_bootstrap(loss, clim_loss) if name != "climatology" else None
        report["variants"][name] = s
    folds = []
    for lo, hi in test_blocks[1:]:
        sl = slice(lo - eval_start, hi - eval_start)
        folds.append({"start": str(ds.kickoff[lo].astype("datetime64[D]")), "n": int(hi - lo),
                      **{k: float(_row_logloss(p[sl], y_eval[sl]).mean()) for k, p in preds.items()}})
    report["folds_log_loss"] = folds
    res.n_oos, res.first_test_index, res.eval_index, res.preds, res.y_eval = len(eval_idx), first, eval_idx, preds, y_eval
    res.oof_raw = {k: v[first:] for k, v in raw.items()}
    res.test_index, res.report = test_idx, report
    return res


def _subset(ds: Dataset, mask: np.ndarray) -> Dataset:
    return Dataset(ds.kickoff[mask], ds.fixture_ids[mask], ds.X[mask], ds.H[mask], ds.goals_home[mask], ds.goals_away[mask],
                   {k: v[mask] for k, v in ds.y.items()}, {k: v[mask] for k, v in ds.mask.items()}, ds.is_demo, ds.skipped)


def select_best(report: dict) -> str | None:
    """Best *trainable* variant by out-of-sample log loss (references are never selected)."""
    if report.get("status") != "ok":
        return None
    cands = {k: v for k, v in report["variants"].items() if k.split("+")[0] not in REFERENCES}
    return min(cands, key=lambda k: cands[k]["log_loss"]) if cands else None


def promotion_decision(report: dict, variant: str | None, is_demo: bool, min_oos: int) -> dict:
    """Gates that must ALL hold for a model to replace the baseline automatically."""
    reasons: list[str] = []
    if variant is None or report.get("status") != "ok":
        return {"eligible": False, "reasons": ["no evaluation available"]}
    v = report["variants"][variant]
    if is_demo:
        reasons.append("trained on synthetic demo data - cannot be promoted automatically")
    if report["n_oos"] < min_oos:
        reasons.append(f"only {report['n_oos']} out-of-sample matches (need {min_oos})")
    vb = v["vs_baseline"]
    if vb is None or vb["ci_high"] is None or vb["ci_high"] >= 0:
        reasons.append("log loss is not significantly better than the Poisson baseline (95% CI includes 0)")
    vc = v["vs_climatology"]
    if vc is not None and (vc["ci_high"] is None or vc["ci_high"] >= 0):
        reasons.append("does not significantly beat the base-rate-only reference")
    base_ece = report["variants"]["poisson_baseline"]["ece"]
    if v["ece"] is not None and base_ece is not None and v["ece"] > max(base_ece, 0.03):
        reasons.append("calibration error is worse than the baseline")
    return {"eligible": not reasons, "reasons": reasons}


__all__ = ["EvalResult", "IdentityCalibrator", "MarketModel", "evaluate", "paired_bootstrap", "promotion_decision", "select_best"]
