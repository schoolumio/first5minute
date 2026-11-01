"""Load trained model artifacts and score fixtures at prediction time."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np

from app.core.config import get_settings
from app.engine.ml.dataset import FEATURES, HIER_FIELDS, feature_row, hier_row
from app.engine.ml.models import IdentityCalibrator, MarketModel
from app.models import Fixture, ModelVersion


@dataclass
class ModelBundle:
    """A fitted model + optional calibrator, persisted together with joblib."""

    market: str
    variant: str                       # e.g. "ensemble+platt"
    model: MarketModel
    calibrator: object = field(default_factory=IdentityCalibrator)
    features: list[str] = field(default_factory=lambda: list(FEATURES))
    meta: dict = field(default_factory=dict)

    def predict_matrix(self, X: np.ndarray, H: np.ndarray) -> np.ndarray:
        return np.asarray(self.calibrator.predict(self.model.predict(X, H)))

    def predict_one(self, analysis, fixture: Fixture) -> float:
        fr, hr = feature_row(analysis, fixture), hier_row(analysis)
        X = np.array([[fr[f] for f in self.features]])
        H = np.array([[hr[f] for f in HIER_FIELDS]])
        return float(self.predict_matrix(X, H)[0])


def artifact_path(market: str, version: str) -> Path:
    return Path(get_settings().model_dir) / market / f"{version}.joblib"


def save_bundle(bundle: ModelBundle, version: str) -> Path:
    path = artifact_path(bundle.market, version)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    return path


_cache: dict[int, ModelBundle] = {}
_lock = threading.Lock()


def load_bundle(mv: ModelVersion) -> ModelBundle:
    """Cached by model-version id (versions are immutable). Raises FileNotFoundError if the artifact is missing."""
    with _lock:
        if mv.id in _cache:
            return _cache[mv.id]
    path = Path((mv.params or {}).get("artifact") or artifact_path(mv.market_code, mv.version))
    if not path.exists():
        raise FileNotFoundError(f"model artifact not found: {path}")
    # Artifacts are produced by this application only (trusted model_dir); never load uploaded files.
    bundle = joblib.load(path)
    with _lock:
        _cache[mv.id] = bundle
    return bundle


def clear_cache() -> None:
    with _lock:
        _cache.clear()
