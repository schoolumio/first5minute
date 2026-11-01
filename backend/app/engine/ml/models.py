"""Candidate probability models and calibrators (one instance per market).

All models share ``fit(ds)`` / ``predict(X, H)`` where ``X``/``H`` are the
feature matrices from :mod:`app.engine.ml.dataset`. They must only ever be
fitted on rows that kicked off before the rows they predict.

* ``BaselineModel``   - the Phase-2 Poisson probability, unchanged (reference).
* ``ClimatologyModel``- training base rate only (skill floor: "no information").
* ``HierPoissonModel``- empirical-Bayes hierarchical Poisson: league -> team
  partial pooling whose shrinkage strength is fitted by predictive
  likelihood of observed early-goal counts (not fixed at 8 as in baseline).
* ``LogisticModel``   - L2-regularised logistic regression on pre-kickoff features.
* ``GBMModel``        - LightGBM boosting on top of the baseline logit (init
  score), small trees and strong regularisation: it can only learn *residuals*
  to the baseline, so tiny samples leave it close to the baseline.
* ``EnsembleModel``   - equal-weight mean in logit space (no fitted weights, so
  no extra look-ahead when evaluated walk-forward).
"""

from __future__ import annotations

import numpy as np
from scipy.special import expit, ive, logit
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.engine.ml.dataset import FEATURES, HIER_FIELDS, Dataset
from app.engine.settlement import Market

EPS = 1e-6
FI = {f: i for i, f in enumerate(FEATURES)}
HI = {f: i for i, f in enumerate(HIER_FIELDS)}
MIN_STRENGTH, MAX_STRENGTH = 0.25, 4.0


def _clip(p):
    return np.clip(p, EPS, 1 - EPS)


class MarketModel:
    name = "base"
    label = "base"

    def __init__(self, market: str):
        self.market = market

    @property
    def base_col(self) -> int:
        return FI["logit_base_a" if self.market == Market.A else "logit_base_b"]

    def fit(self, ds: Dataset) -> MarketModel:
        return self

    def predict(self, X: np.ndarray, H: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class BaselineModel(MarketModel):
    name, label = "poisson_baseline", "Poisson baseline"

    def predict(self, X, H):
        return _clip(expit(X[:, self.base_col]))


class ClimatologyModel(MarketModel):
    name, label = "climatology", "Base rate only"

    def fit(self, ds):
        self.rate = float(np.mean(ds.y[self.market])) if len(ds) else 0.5
        return self

    def predict(self, X, H):
        return np.full(len(X), self.rate)


def _lambdas(H: np.ndarray, k: float) -> tuple[np.ndarray, np.ndarray]:
    lg_h, lg_a = H[:, HI["lg_home"]], H[:, HI["lg_away"]]
    base = (lg_h + lg_a) / 2
    def rate(total, n):
        return (total + k * base) / (n + k)
    h_att, h_def = rate(H[:, HI["h_for"]], H[:, HI["h_n"]]), rate(H[:, HI["h_against"]], H[:, HI["h_n"]])
    a_att, a_def = rate(H[:, HI["a_for"]], H[:, HI["a_n"]]), rate(H[:, HI["a_against"]], H[:, HI["a_n"]])
    c = lambda v: np.clip(v / base, MIN_STRENGTH, MAX_STRENGTH)  # noqa: E731
    return lg_h * c(h_att) * c(a_def), lg_a * c(a_att) * c(h_def)


def market_probs(market: str, lam_h: np.ndarray, lam_a: np.ndarray) -> np.ndarray:
    tot = lam_h + lam_a
    if market == Market.A:
        return np.exp(-tot)
    x = 2 * np.sqrt(lam_h * lam_a)
    return ive(0, x) * np.exp(x - tot)


class HierPoissonModel(MarketModel):
    name, label = "hier_eb_poisson", "Hierarchical Poisson (empirical Bayes)"
    K_GRID = (0.5, 1, 2, 3, 5, 8, 12, 16, 24, 32, 48, 64, 100, 200)

    def fit(self, ds):
        if len(ds) < 20:
            self.k = 8.0
            return self
        best, best_ll = 8.0, -np.inf
        for k in self.K_GRID:
            lh, la = _lambdas(ds.H, k)
            lh, la = np.maximum(lh, 1e-9), np.maximum(la, 1e-9)
            ll = float(np.sum(ds.goals_home * np.log(lh) - lh + ds.goals_away * np.log(la) - la))
            if ll > best_ll:
                best, best_ll = k, ll
        self.k = best
        return self

    def predict(self, X, H):
        lh, la = _lambdas(H, self.k)
        return _clip(market_probs(self.market, lh, la))


class LogisticModel(MarketModel):
    name, label = "logistic", "Logistic regression"

    def __init__(self, market: str, C: float = 0.1):
        super().__init__(market)
        self.C = C

    def _cols(self) -> list[int]:
        return list(range(len(FEATURES)))

    def fit(self, ds):
        y = ds.y[self.market]
        if len(ds) < 30 or len(set(y.tolist())) < 2:
            self.pipe = None
            self.fallback = float(np.mean(y)) if len(y) else 0.5
            return self
        self.pipe = make_pipeline(StandardScaler(), LogisticRegression(C=self.C, max_iter=2000))
        self.pipe.fit(ds.X[:, self._cols()], y)
        return self

    def predict(self, X, H):
        if self.pipe is None:
            return np.full(len(X), self.fallback)
        return _clip(self.pipe.predict_proba(X[:, self._cols()])[:, 1])


class GBMModel(MarketModel):
    name, label = "lightgbm_residual", "LightGBM (residual to baseline)"

    def __init__(self, market: str, **overrides):
        super().__init__(market)
        self.params = dict(n_estimators=120, learning_rate=0.03, num_leaves=4, max_depth=3, min_child_samples=25,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, random_state=5,
                           verbose=-1, n_jobs=1) | overrides

    def fit(self, ds):
        import lightgbm as lgb

        y = ds.y[self.market]
        if len(ds) < 60 or len(set(y.tolist())) < 2:
            self.gbm = None
            return self
        self.gbm = lgb.LGBMClassifier(**self.params)
        X = np.ascontiguousarray(ds.X)
        self.gbm.fit(X, y, init_score=np.ascontiguousarray(X[:, self.base_col]))
        return self

    def predict(self, X, H):
        if self.gbm is None:
            return _clip(expit(X[:, self.base_col]))
        return _clip(expit(self.gbm.predict(np.ascontiguousarray(X), raw_score=True) + X[:, self.base_col]))


class EnsembleModel(MarketModel):
    name, label = "ensemble", "Ensemble (equal-weight logit mean)"

    def __init__(self, market: str, members: list[MarketModel] | None = None):
        super().__init__(market)
        self.members = members or [HierPoissonModel(market), LogisticModel(market), GBMModel(market)]

    def fit(self, ds):
        for m in self.members:
            m.fit(ds)
        return self

    def predict(self, X, H):
        z = np.mean([logit(_clip(m.predict(X, H))) for m in self.members], axis=0)
        return _clip(expit(z))


# ---------------------------------------------------------------- calibration
class IdentityCalibrator:
    name = "none"

    def fit(self, p, y):
        return self

    def predict(self, p):
        return np.asarray(p)


class PlattCalibrator:
    """Logistic recalibration on the logit of the model probability (2 parameters)."""

    name = "platt"

    def fit(self, p, y):
        z = logit(_clip(np.asarray(p))).reshape(-1, 1)
        self.lr = LogisticRegression(C=1e6, max_iter=1000).fit(z, y) if len(set(np.asarray(y).tolist())) > 1 else None
        self.const = float(np.mean(y)) if self.lr is None and len(y) else None
        return self

    def predict(self, p):
        p = np.asarray(p)
        if self.lr is None:
            return np.full(len(p), self.const if self.const is not None else 0.5)
        return _clip(self.lr.predict_proba(logit(_clip(p)).reshape(-1, 1))[:, 1])


class IsotonicCalibrator:
    name = "isotonic"

    def fit(self, p, y):
        self.iso = IsotonicRegression(y_min=EPS, y_max=1 - EPS, out_of_bounds="clip").fit(np.asarray(p), np.asarray(y))
        return self

    def predict(self, p):
        return _clip(self.iso.predict(np.asarray(p)))


def make_calibrator(n_samples: int, isotonic_min: int = 800):
    """Platt for small samples (few parameters), isotonic only when plentiful data supports it."""
    if n_samples < 60:
        return IdentityCalibrator()
    return IsotonicCalibrator() if n_samples >= isotonic_min else PlattCalibrator()


def candidate_models(market: str) -> dict[str, MarketModel]:
    members = [HierPoissonModel(market), LogisticModel(market), GBMModel(market)]
    return {
        "poisson_baseline": BaselineModel(market),
        "climatology": ClimatologyModel(market),
        "hier_eb_poisson": members[0],
        "logistic": members[1],
        "lightgbm_residual": members[2],
        "ensemble": EnsembleModel(market, [HierPoissonModel(market), LogisticModel(market), GBMModel(market)]),
    }
