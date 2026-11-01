"""Probabilistic forecast evaluation metrics (pure functions)."""

from __future__ import annotations

import math
from collections.abc import Sequence

EPS = 1e-12


def brier_score(probs: Sequence[float], outcomes: Sequence[int]) -> float | None:
    if not probs:
        return None
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes, strict=True)) / len(probs)


def log_loss(probs: Sequence[float], outcomes: Sequence[int]) -> float | None:
    if not probs:
        return None
    total = 0.0
    for p, y in zip(probs, outcomes, strict=True):
        p = min(max(p, EPS), 1 - EPS)
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(probs)


def calibration_bins(probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> list[dict]:
    """Reliability-diagram data: mean predicted vs observed frequency per bin."""
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, y in zip(probs, outcomes, strict=True):
        idx = min(int(p * n_bins), n_bins - 1)
        bins[idx].append((p, y))
    out = []
    for i, b in enumerate(bins):
        if not b:
            continue
        out.append(
            {
                "bin_start": i / n_bins,
                "bin_end": (i + 1) / n_bins,
                "count": len(b),
                "mean_predicted": sum(p for p, _ in b) / len(b),
                "observed_rate": sum(y for _, y in b) / len(b),
            }
        )
    return out


def expected_calibration_error(probs: Sequence[float], outcomes: Sequence[int], n_bins: int = 10) -> float | None:
    if not probs:
        return None
    n = len(probs)
    return sum(b["count"] / n * abs(b["mean_predicted"] - b["observed_rate"]) for b in calibration_bins(probs, outcomes, n_bins))


def precision_recall(probs: Sequence[float], outcomes: Sequence[int], threshold: float) -> dict:
    tp = sum(1 for p, y in zip(probs, outcomes, strict=True) if p >= threshold and y == 1)
    fp = sum(1 for p, y in zip(probs, outcomes, strict=True) if p >= threshold and y == 0)
    fn = sum(1 for p, y in zip(probs, outcomes, strict=True) if p < threshold and y == 1)
    return {
        "threshold": threshold,
        "selected": tp + fp,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def accuracy(probs: Sequence[float], outcomes: Sequence[int], threshold: float = 0.5) -> float | None:
    if not probs:
        return None
    return sum(1 for p, y in zip(probs, outcomes, strict=True) if (p >= threshold) == (y == 1)) / len(probs)


def roi_simulation(selections: Sequence[tuple[float, int]], stake: float = 1.0) -> dict:
    """Flat-stake ROI on (decimal_odds, won) pairs from *real* recorded odds only."""
    n = len(selections)
    if n == 0:
        return {"bets": 0, "profit": 0.0, "roi": None}
    profit = sum((odds - 1) * stake if won else -stake for odds, won in selections)
    return {"bets": n, "profit": round(profit, 4), "roi": profit / (n * stake)}


def summarize(probs: Sequence[float], outcomes: Sequence[int], threshold: float) -> dict:
    return {
        "sample_size": len(probs),
        "base_rate": (sum(outcomes) / len(outcomes)) if outcomes else None,
        "mean_predicted": (sum(probs) / len(probs)) if probs else None,
        "brier": brier_score(probs, outcomes),
        "log_loss": log_loss(probs, outcomes),
        "ece": expected_calibration_error(probs, outcomes),
        "accuracy": accuracy(probs, outcomes, threshold),
        **{k: v for k, v in precision_recall(probs, outcomes, threshold).items() if k != "threshold"},
        "threshold": threshold,
        "calibration": calibration_bins(probs, outcomes),
    }
