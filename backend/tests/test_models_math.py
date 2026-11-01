"""Prediction calculations and metrics (pure unit tests)."""

import math

import pytest
from scipy.stats import poisson

from app.engine import metrics
from app.engine.poisson import (
    GLOBAL_BASELINE,
    LeagueBaseline,
    TeamHistoryRecord,
    blend_league_baseline,
    expected_goals,
    level_components,
    predict_markets,
    prob_level,
    prob_no_goal,
    smoothed_team_rates,
)


def test_model_a_is_poisson_zero():
    assert prob_no_goal(0.1, 0.05) == pytest.approx(math.exp(-0.15))
    assert prob_no_goal(0, 0) == 1.0
    with pytest.raises(ValueError):
        prob_no_goal(-0.1, 0)


@pytest.mark.parametrize("lh,la", [(0.08, 0.06), (0.5, 0.3), (2.0, 1.5), (0.0, 0.2)])
def test_model_b_matches_brute_force_sum(lh, la):
    brute = sum(poisson.pmf(k, lh) * poisson.pmf(k, la) for k in range(60))
    assert prob_level(lh, la) == pytest.approx(brute, rel=1e-9)


def test_model_b_exceeds_model_a_and_components_sum():
    lh, la = 0.3, 0.2
    assert prob_level(lh, la) > prob_no_goal(lh, la)
    comps = level_components(lh, la)
    assert comps["0-0"] == pytest.approx(prob_no_goal(lh, la))
    assert sum(comps.values()) == pytest.approx(prob_level(lh, la))
    assert comps["1-1"] == pytest.approx(poisson.pmf(1, lh) * poisson.pmf(1, la))


def test_smoothing_shrinks_to_prior_with_no_data():
    r = smoothed_team_rates([], prior_for=0.07, prior_against=0.06)
    assert r.scoring_rate == pytest.approx(0.07)
    assert r.conceding_rate == pytest.approx(0.06)
    assert r.sample_size == 0 and r.raw_scoring_rate is None


def test_smoothing_moves_toward_data_as_sample_grows():
    hist = [TeamHistoryRecord(True, 1, 0)] * 40
    small = smoothed_team_rates(hist[:3], 0.07, 0.07, prior_strength=8, half_life=1000)
    large = smoothed_team_rates(hist, 0.07, 0.07, prior_strength=8, half_life=1000, max_history=40)
    assert 0.07 < small.scoring_rate < large.scoring_rate < 1.0
    assert large.raw_scoring_rate == 1.0 and large.scored_early_pct == 1.0


def test_recent_matches_weigh_more():
    recent_goals = [TeamHistoryRecord(True, 1, 0)] * 5 + [TeamHistoryRecord(True, 0, 0)] * 15
    old_goals = [TeamHistoryRecord(True, 0, 0)] * 15 + [TeamHistoryRecord(True, 1, 0)] * 5
    a = smoothed_team_rates(recent_goals, 0.07, 0.07, half_life=5)
    b = smoothed_team_rates(old_goals, 0.07, 0.07, half_life=5)
    assert a.scoring_rate > b.scoring_rate


def test_unreliable_matches_excluded_but_counted_for_reliability():
    hist = [TeamHistoryRecord(True, 1, 0, reliable=False)] * 4 + [TeamHistoryRecord(True, 0, 0)] * 6
    r = smoothed_team_rates(hist, 0.07, 0.07)
    assert r.sample_size == 6 and r.total_considered == 10
    assert r.reliability == pytest.approx(0.6)
    assert r.raw_scoring_rate == 0


def test_average_teams_reproduce_league_baseline():
    league = LeagueBaseline(home_rate=0.08, away_rate=0.06, sample_size=200)
    avg = smoothed_team_rates([], league.per_team_rate, league.per_team_rate)
    lam = expected_goals(avg, avg, league)
    assert lam.home == pytest.approx(0.08) and lam.away == pytest.approx(0.06)
    probs = predict_markets(avg, avg, league)
    assert probs.market_a == pytest.approx(math.exp(-0.14))


def test_league_baseline_blending():
    tiny = blend_league_baseline(home_goals=5, away_goals=5, matches=5, min_sample=40)
    assert abs(tiny.home_rate - GLOBAL_BASELINE.home_rate) < abs(1.0 - GLOBAL_BASELINE.home_rate)
    big = blend_league_baseline(home_goals=1000, away_goals=0, matches=10000, min_sample=40)
    assert big.home_rate == pytest.approx(0.1, rel=0.01)


def test_metrics_known_values():
    assert metrics.brier_score([1.0, 0.0], [1, 0]) == 0
    assert metrics.brier_score([0.5, 0.5], [1, 0]) == 0.25
    assert metrics.log_loss([0.5], [1]) == pytest.approx(math.log(2))
    assert metrics.brier_score([], []) is None
    bins = metrics.calibration_bins([0.05, 0.95, 0.91], [0, 1, 0])
    assert [b["count"] for b in bins] == [1, 2]
    assert bins[1]["observed_rate"] == 0.5
    pr = metrics.precision_recall([0.9, 0.95, 0.5], [1, 0, 1], 0.9)
    assert pr["precision"] == 0.5 and pr["recall"] == 0.5


def test_roi_uses_only_given_odds():
    assert metrics.roi_simulation([]) == {"bets": 0, "profit": 0.0, "roi": None}
    r = metrics.roi_simulation([(1.2, True), (1.2, False)])
    assert r["profit"] == pytest.approx(-0.8) and r["roi"] == pytest.approx(-0.4)
