"""Turn a fixture into market predictions with quality, confidence and category."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.engine.features import (
    FEATURE_SET_VERSION,
    TeamHistory,
    input_data_version,
    league_baseline,
    team_history,
)
from app.engine.poisson import (
    LeagueBaseline,
    MarketProbabilities,
    TeamRates,
    predict_markets,
    smoothed_team_rates,
)
from app.engine.settlement import Market
from app.models import Fixture

DQ_ORDER = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}
CATEGORIES = ("qualified", "watchlist", "below_threshold", "excluded")


@dataclass(slots=True)
class FixtureAnalysis:
    fixture_id: int
    home_rates: TeamRates
    away_rates: TeamRates
    league: LeagueBaseline
    probs: MarketProbabilities
    data_quality: str
    data_quality_reasons: list[str]
    input_version: str
    uncertainty: dict[str, float]
    params: dict
    home_history: TeamHistory
    away_history: TeamHistory
    feature_set_version: str = FEATURE_SET_VERSION
    extra: dict = field(default_factory=dict)

    def probability(self, market: str) -> float:
        return self.probs.market_a if market == Market.A else self.probs.market_b

    @property
    def min_sample(self) -> int:
        return min(self.home_rates.sample_size, self.away_rates.sample_size)


def assess_data_quality(home: TeamRates, away: TeamRates, league: LeagueBaseline, thresholds: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    min_n = min(home.sample_size, away.sample_size)
    reliability = min(home.reliability, away.reliability) if min(home.total_considered, away.total_considered) else 0.0
    if min_n < thresholds.get("watchlist_min_team_sample", 5):
        reasons.append(f"insufficient reliable event history (min team sample {min_n})")
        return "insufficient", reasons
    if reliability < 0.75:
        reasons.append(f"only {reliability:.0%} of recent matches have a reconciled event timeline")
    if league.sample_size < 40:
        reasons.append(f"small competition baseline sample ({league.sample_size})")
    if min_n >= 15 and reliability >= 0.9 and league.sample_size >= 100:
        return "high", reasons
    if min_n >= 10 and reliability >= 0.75:
        return "medium", reasons
    return "low", reasons


def probability_uncertainty(home: TeamRates, away: TeamRates, probs: MarketProbabilities, prior_strength: float) -> dict:
    """Approximate posterior SD of each market probability (delta method).

    Each smoothed rate is a Gamma posterior mean with shape alpha = rate * (n_eff + k);
    its coefficient of variation is 1/sqrt(alpha).
    """

    def cv(rate: float, rates: TeamRates) -> float:
        alpha = max(rate * (rates.effective_sample + prior_strength), 1e-9)
        return 1 / math.sqrt(alpha)

    lam = probs.lambdas
    cv_h = math.hypot(cv(home.scoring_rate, home), cv(away.conceding_rate, away))
    cv_a = math.hypot(cv(away.scoring_rate, away), cv(home.conceding_rate, home))
    sd_total = math.hypot(lam.home * cv_h, lam.away * cv_a)
    sd_a = probs.market_a * sd_total  # dP/dlambda = -P
    # Model B is dominated by the 0-0 term; same delta approximation is a fair upper bound.
    sd_b = probs.market_b * sd_total
    return {"MARKET_A": round(sd_a, 5), "MARKET_B": round(sd_b, 5), "lambda_total_sd": round(sd_total, 5)}


# Five-minute goal counts are rare events, so even long histories leave wide
# posterior uncertainty on team rates. Labels are relative to that reality.
CONFIDENCE_SD_HIGH = 0.05
CONFIDENCE_SD_MEDIUM = 0.09


def confidence_label(sd: float) -> str:
    """Map the approximate posterior SD of the probability to a label."""
    if sd < CONFIDENCE_SD_HIGH:
        return "high"
    if sd < CONFIDENCE_SD_MEDIUM:
        return "medium"
    return "low"


def categorize(analysis: FixtureAnalysis, market: str, thresholds: dict) -> tuple[str, list[str]]:
    p = analysis.probability(market)
    mt = thresholds.get(market, {})
    reasons = list(analysis.data_quality_reasons)
    if analysis.data_quality == "insufficient":
        return "excluded", reasons
    q_min, w_min = mt.get("qualified_min_probability", 1.0), mt.get("watchlist_min_probability", 1.0)
    q_sample = thresholds.get("qualified_min_team_sample", 10)
    q_dq = thresholds.get("qualified_min_data_quality", "medium")
    if p >= q_min and analysis.min_sample >= q_sample and DQ_ORDER[analysis.data_quality] >= DQ_ORDER[q_dq]:
        return "qualified", reasons
    if p >= w_min:
        if p >= q_min:
            reasons.append("probability meets qualified threshold but sample/data quality does not")
        return "watchlist", reasons
    reasons.append(f"estimated probability {p:.3f} below watchlist threshold {w_min:.3f}")
    return "below_threshold", reasons


def analyse_fixture(db: Session, fixture: Fixture, params: dict, thresholds: dict) -> FixtureAnalysis:
    as_of = fixture.kickoff_at
    k = float(params.get("prior_strength", 8.0))
    max_hist = int(params.get("max_history", 20))
    half_life = float(params.get("half_life_matches", 10.0))
    league = league_baseline(db, fixture.competition_id, as_of, int(params.get("competition_min_sample", 40)))
    hh = team_history(db, fixture.home_team_id, as_of, max_hist)
    ah = team_history(db, fixture.away_team_id, as_of, max_hist)
    # Priors: the league's per-team rate for both scoring and conceding.
    prior = league.per_team_rate
    home_rates = smoothed_team_rates(hh.records, prior, prior, k, half_life, max_hist)
    away_rates = smoothed_team_rates(ah.records, prior, prior, k, half_life, max_hist)
    probs = predict_markets(home_rates, away_rates, league)
    dq, reasons = assess_data_quality(home_rates, away_rates, league, thresholds)
    return FixtureAnalysis(
        fixture_id=fixture.id,
        home_rates=home_rates,
        away_rates=away_rates,
        league=league,
        probs=probs,
        data_quality=dq,
        data_quality_reasons=reasons,
        input_version=input_data_version(fixture, hh, ah, league, params),
        uncertainty=probability_uncertainty(home_rates, away_rates, probs, k),
        params=params,
        home_history=hh,
        away_history=ah,
    )
