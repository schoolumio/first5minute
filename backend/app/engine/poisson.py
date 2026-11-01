"""Baseline Poisson models for the two five-minute markets.

Model A - no goal before the cutoff:
    G_home ~ Poisson(lambda_home), G_away ~ Poisson(lambda_away), independent
    P(no goal) = P(G_home + G_away = 0) = exp(-(lambda_home + lambda_away))

Model B - level score at the cutoff:
    P(G_home = G_away) = sum_k P(G_home = k) P(G_away = k)
                       = exp(-(lh + la)) * I0(2 * sqrt(lh * la))
    where I0 is the modified Bessel function of the first kind (order 0).
    We also expose the 0-0, 1-1, 2-2 and "other level" components.

Expected goals in the window combine team attack/defence strengths with the
competition baseline (multiplicative strength model):
    lambda_home = league_home_rate * attack(home) * defence(away)
    lambda_away = league_away_rate * attack(away) * defence(home)
with attack(t) = smoothed early scoring rate / league per-team rate and
defence(t) = smoothed early conceding rate / league per-team rate. Small
samples are shrunk toward the league baseline by a Gamma-Poisson (Bayesian)
prior; recent matches carry more weight via an exponential decay.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.special import ive
from scipy.stats import poisson

# Strength multipliers are clamped so a tiny/odd sample cannot explode lambda.
MIN_STRENGTH, MAX_STRENGTH = 0.25, 4.0


@dataclass(frozen=True, slots=True)
class TeamHistoryRecord:
    """One past match from a team's perspective (only pre-kickoff data)."""

    is_home: bool
    early_for: int
    early_against: int
    reliable: bool = True


@dataclass(frozen=True, slots=True)
class TeamRates:
    sample_size: int  # reliable matches used
    total_considered: int  # including unreliable timelines
    effective_sample: float  # sum of recency weights
    scoring_rate: float  # smoothed expected early goals scored per match
    conceding_rate: float
    raw_scoring_rate: float | None
    raw_conceding_rate: float | None
    scored_early_pct: float | None  # share of matches with >=1 early goal scored
    conceded_early_pct: float | None
    clean_window_pct: float | None  # share of matches 0-0 at cutoff

    @property
    def reliability(self) -> float:
        return self.sample_size / self.total_considered if self.total_considered else 0.0


@dataclass(frozen=True, slots=True)
class LeagueBaseline:
    home_rate: float  # early goals per match scored by home sides
    away_rate: float
    sample_size: int
    clean_window_pct: float | None = None

    @property
    def per_team_rate(self) -> float:
        return (self.home_rate + self.away_rate) / 2


# Global prior used when a competition has little history: ~2.7 goals per 90
# minutes split 55/45 home/away, scaled to a 5-minute window.
GLOBAL_BASELINE = LeagueBaseline(home_rate=2.7 * 0.55 * 5 / 90, away_rate=2.7 * 0.45 * 5 / 90, sample_size=0)


def smoothed_team_rates(
    history: list[TeamHistoryRecord],
    prior_for: float,
    prior_against: float,
    prior_strength: float = 8.0,
    half_life: float = 10.0,
    max_history: int = 20,
) -> TeamRates:
    """Recency-weighted Gamma-Poisson posterior mean of early goal rates.

    ``history`` must be ordered most-recent first and contain only matches
    that kicked off before the fixture being predicted.
    """
    considered = history[:max_history]
    reliable = [h for h in considered if h.reliable]
    w_sum = sf = sa = 0.0
    for i, rec in enumerate(reliable):
        w = 0.5 ** (i / half_life) if half_life > 0 else 1.0
        w_sum += w
        sf += w * rec.early_for
        sa += w * rec.early_against
    scoring = (sf + prior_strength * prior_for) / (w_sum + prior_strength)
    conceding = (sa + prior_strength * prior_against) / (w_sum + prior_strength)
    n = len(reliable)
    return TeamRates(
        sample_size=n,
        total_considered=len(considered),
        effective_sample=round(w_sum, 3),
        scoring_rate=scoring,
        conceding_rate=conceding,
        raw_scoring_rate=(sum(r.early_for for r in reliable) / n) if n else None,
        raw_conceding_rate=(sum(r.early_against for r in reliable) / n) if n else None,
        scored_early_pct=(sum(1 for r in reliable if r.early_for > 0) / n) if n else None,
        conceded_early_pct=(sum(1 for r in reliable if r.early_against > 0) / n) if n else None,
        clean_window_pct=(sum(1 for r in reliable if r.early_for == 0 and r.early_against == 0) / n) if n else None,
    )


def blend_league_baseline(
    home_goals: int, away_goals: int, matches: int, min_sample: int = 40, prior: LeagueBaseline = GLOBAL_BASELINE
) -> LeagueBaseline:
    """Competition baseline shrunk toward the global prior for small samples."""
    m = float(min_sample)
    home = (home_goals + m * prior.home_rate) / (matches + m)
    away = (away_goals + m * prior.away_rate) / (matches + m)
    return LeagueBaseline(home_rate=home, away_rate=away, sample_size=matches)


def _clamp(x: float) -> float:
    return max(MIN_STRENGTH, min(MAX_STRENGTH, x))


@dataclass(frozen=True, slots=True)
class Lambdas:
    home: float
    away: float
    attack_home: float
    defence_home: float
    attack_away: float
    defence_away: float

    @property
    def total(self) -> float:
        return self.home + self.away


def expected_goals(home: TeamRates, away: TeamRates, league: LeagueBaseline) -> Lambdas:
    base = league.per_team_rate or GLOBAL_BASELINE.per_team_rate
    att_h = _clamp(home.scoring_rate / base)
    def_h = _clamp(home.conceding_rate / base)
    att_a = _clamp(away.scoring_rate / base)
    def_a = _clamp(away.conceding_rate / base)
    return Lambdas(
        home=league.home_rate * att_h * def_a,
        away=league.away_rate * att_a * def_h,
        attack_home=att_h,
        defence_home=def_h,
        attack_away=att_a,
        defence_away=def_a,
    )


def prob_no_goal(lam_home: float, lam_away: float) -> float:
    """Model A: P(total goals in window = 0)."""
    if lam_home < 0 or lam_away < 0:
        raise ValueError("lambda must be non-negative")
    return math.exp(-(lam_home + lam_away))


def prob_level(lam_home: float, lam_away: float) -> float:
    """Model B: P(home goals == away goals) via the Bessel closed form.

    ``ive(0, x) = I0(x) * exp(-|x|)`` keeps the computation numerically stable.
    """
    if lam_home < 0 or lam_away < 0:
        raise ValueError("lambda must be non-negative")
    x = 2.0 * math.sqrt(lam_home * lam_away)
    return float(ive(0, x) * math.exp(x - (lam_home + lam_away)))


def level_components(lam_home: float, lam_away: float, max_k: int = 2) -> dict[str, float]:
    comps = {f"{k}-{k}": float(poisson.pmf(k, lam_home) * poisson.pmf(k, lam_away)) for k in range(max_k + 1)}
    total = prob_level(lam_home, lam_away)
    comps["other_level"] = max(0.0, total - sum(comps.values()))
    return comps


@dataclass(slots=True)
class MarketProbabilities:
    market_a: float
    market_b: float
    lambdas: Lambdas
    components_b: dict[str, float] = field(default_factory=dict)


def predict_markets(home: TeamRates, away: TeamRates, league: LeagueBaseline) -> MarketProbabilities:
    lam = expected_goals(home, away, league)
    return MarketProbabilities(
        market_a=prob_no_goal(lam.home, lam.away),
        market_b=prob_level(lam.home, lam.away),
        lambdas=lam,
        components_b=level_components(lam.home, lam.away),
    )
