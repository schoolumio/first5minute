"""Leak-free training dataset for the advanced models.

One row per *finished* fixture whose timeline reconciles with its final
score. Every feature is computed by the same code path as live predictions
(``analyse_fixture``), which only reads matches that kicked off strictly
before the fixture. Labels (settled outcome of each market) are the only
post-kickoff information and are never part of the feature vector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engine.poisson import prob_level, prob_no_goal
from app.engine.predictor import FixtureAnalysis, analyse_fixture
from app.engine.settlement import Market, Result, score_at_cutoff, settle
from app.ingestion.service import Ingestor
from app.models import Fixture, MatchEvent
from app.services.settings import default_rule_row, get_setting, rule_from_row

FEATURES = [
    "logit_base_a", "logit_base_b", "lam_home", "lam_away", "lam_total",
    "att_home", "def_home", "att_away", "def_away",
    "home_score_rate", "home_concede_rate", "away_score_rate", "away_concede_rate",
    "home_scored_pct", "home_conceded_pct", "home_clean_pct",
    "away_scored_pct", "away_conceded_pct", "away_clean_pct",
    "sample_home", "sample_away", "reliability_min",
    "league_home_rate", "league_away_rate", "league_clean_pct", "league_sample", "is_women",
]
# Raw team sums for the hierarchical (partial-pooling) model.
HIER_FIELDS = ["h_for", "h_against", "h_n", "a_for", "a_against", "a_n", "lg_home", "lg_away"]


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return float(np.log(p / (1 - p)))


def feature_row(analysis: FixtureAnalysis, fixture: Fixture) -> dict[str, float]:
    """Pre-kickoff feature vector (dict) for one fixture. Missing history falls back to league rates."""
    h, a, lam, lg = analysis.home_rates, analysis.away_rates, analysis.probs.lambdas, analysis.league
    clean = lg.clean_window_pct if lg.clean_window_pct is not None else float(np.exp(-(lg.home_rate + lg.away_rate)))

    def pc(v: float | None, default: float) -> float:
        return default if v is None else float(v)

    return {
        "logit_base_a": _logit(analysis.probs.market_a), "logit_base_b": _logit(analysis.probs.market_b),
        "lam_home": lam.home, "lam_away": lam.away, "lam_total": lam.total,
        "att_home": lam.attack_home, "def_home": lam.defence_home, "att_away": lam.attack_away, "def_away": lam.defence_away,
        "home_score_rate": h.scoring_rate, "home_concede_rate": h.conceding_rate,
        "away_score_rate": a.scoring_rate, "away_concede_rate": a.conceding_rate,
        "home_scored_pct": pc(h.scored_early_pct, 0.0), "home_conceded_pct": pc(h.conceded_early_pct, 0.0),
        "home_clean_pct": pc(h.clean_window_pct, clean),
        "away_scored_pct": pc(a.scored_early_pct, 0.0), "away_conceded_pct": pc(a.conceded_early_pct, 0.0),
        "away_clean_pct": pc(a.clean_window_pct, clean),
        "sample_home": float(h.sample_size), "sample_away": float(a.sample_size),
        "reliability_min": min(h.reliability, a.reliability),
        "league_home_rate": lg.home_rate, "league_away_rate": lg.away_rate, "league_clean_pct": clean,
        "league_sample": float(lg.sample_size), "is_women": 1.0 if fixture.competition.gender == "women" else 0.0,
    }


def hier_row(analysis: FixtureAnalysis) -> dict[str, float]:
    """Unweighted early-goal sums over each team's reliable history (inputs of the pooling model)."""
    def sums(records) -> tuple[float, float, float]:
        rel = [r for r in records if r.reliable]
        return float(sum(r.early_for for r in rel)), float(sum(r.early_against for r in rel)), float(len(rel))

    hf, ha, hn = sums(analysis.home_history.records)
    af, aa, an = sums(analysis.away_history.records)
    return {"h_for": hf, "h_against": ha, "h_n": hn, "a_for": af, "a_against": aa, "a_n": an,
            "lg_home": analysis.league.home_rate, "lg_away": analysis.league.away_rate}


@dataclass
class Dataset:
    kickoff: np.ndarray                        # datetime64[ns], ascending
    fixture_ids: np.ndarray
    X: np.ndarray                              # (n, len(FEATURES))
    H: np.ndarray                              # (n, len(HIER_FIELDS))
    goals_home: np.ndarray                     # early goals (counts) - label only
    goals_away: np.ndarray
    y: dict[str, np.ndarray] = field(default_factory=dict)       # market -> 0/1 (NaN-free; rows mask below)
    mask: dict[str, np.ndarray] = field(default_factory=dict)    # market -> usable rows
    is_demo: bool = False
    skipped: dict[str, int] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.fixture_ids)

    def market(self, market: str) -> Dataset:
        m = self.mask[market]
        return Dataset(self.kickoff[m], self.fixture_ids[m], self.X[m], self.H[m], self.goals_home[m], self.goals_away[m],
                       {market: self.y[market][m]}, {market: np.ones(m.sum(), bool)}, self.is_demo, self.skipped)


def build_dataset(db: Session, start: datetime | None = None, end: datetime | None = None, min_team_sample: int = 5) -> Dataset:
    params = get_setting(db, "model.baseline")
    thresholds = get_setting(db, "scanner.thresholds")
    rule = rule_from_row(default_rule_row(db))
    q = select(Fixture).where(Fixture.status == "finished", Fixture.timeline_status == "complete").order_by(Fixture.kickoff_at, Fixture.id)
    if start:
        q = q.where(Fixture.kickoff_at >= start)
    if end:
        q = q.where(Fixture.kickoff_at < end)
    skipped = {"insufficient_history": 0, "unresolved": 0}
    ks, ids, X, H, gh, ga = [], [], [], [], [], []
    ys: dict[str, list[int]] = {m.value: [] for m in Market}
    any_demo = False
    for fx in db.scalars(q):
        analysis = analyse_fixture(db, fx, params, thresholds)
        if analysis.min_sample < min_team_sample:
            skipped["insufficient_history"] += 1
            continue
        events = db.scalars(select(MatchEvent).where(MatchEvent.fixture_id == fx.id)).all()
        goals = Ingestor.goal_timings(fx, events)
        cut = score_at_cutoff(goals, rule)
        if not cut.resolved:
            skipped["unresolved"] += 1
            continue
        results = {m: settle(m, fx.status, goals, rule, True)[0] for m in Market}
        if any(r not in (Result.WON, Result.LOST) for r in results.values()):
            skipped["unresolved"] += 1
            continue
        any_demo = any_demo or fx.is_demo
        fr, hr = feature_row(analysis, fx), hier_row(analysis)
        ks.append(np.datetime64(fx.kickoff_at.replace(tzinfo=None), "ns"))
        ids.append(fx.id)
        X.append([fr[f] for f in FEATURES])
        H.append([hr[f] for f in HIER_FIELDS])
        gh.append(cut.home)
        ga.append(cut.away)
        for m in Market:
            ys[m.value].append(int(results[m] is Result.WON))
    n = len(ids)
    ds = Dataset(np.array(ks, dtype="datetime64[ns]"), np.array(ids), np.array(X, dtype=float).reshape(n, len(FEATURES)),
                 np.array(H, dtype=float).reshape(n, len(HIER_FIELDS)), np.array(gh, dtype=float), np.array(ga, dtype=float),
                 is_demo=any_demo, skipped=skipped)
    for m, v in ys.items():
        ds.y[m] = np.array(v, dtype=int)
        ds.mask[m] = np.ones(n, bool)
    return ds


def baseline_probability(market: str, lam_home: float, lam_away: float) -> float:
    return prob_no_goal(lam_home, lam_away) if market == Market.A else prob_level(lam_home, lam_away)
