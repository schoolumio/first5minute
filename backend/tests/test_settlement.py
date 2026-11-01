"""Five-minute cutoff rules (pure unit tests)."""

import pytest

from app.engine.settlement import (
    GoalTiming,
    Market,
    Result,
    Rule,
    goal_window_position,
    score_at_cutoff,
    settle,
    timeline_consistent,
)

STD = Rule()  # 00:00-04:59, ordinal minutes
ELAPSED = Rule(code="EL", minute_convention="elapsed")


def g(side, minute, **kw):
    return GoalTiming(scoring_side=side, period=kw.pop("period", "1H"), minute=minute, **kw)


@pytest.mark.parametrize("minute,expected", [(1, "inside"), (4, "inside"), (5, "inside"), (6, "outside"), (45, "outside")])
def test_ordinal_minutes(minute, expected):
    # Ordinal: minute 5 covers 04:00-04:59, which is inside a 300s window.
    assert goal_window_position(g("home", minute), STD) == expected


@pytest.mark.parametrize("minute,expected", [(0, "inside"), (4, "inside"), (5, "outside")])
def test_elapsed_minutes(minute, expected):
    assert goal_window_position(g("home", minute), ELAPSED) == expected


def test_second_precision_is_exact():
    assert goal_window_position(g("home", 5, second=299), STD) == "inside"
    assert goal_window_position(g("home", 6, second=300), STD) == "outside"


def test_ambiguous_minute_straddling_cutoff():
    # A cutoff at 04:30 cannot be settled from minute-level data for a 5th-minute goal.
    rule = Rule(cutoff_seconds=270)
    assert goal_window_position(g("home", 5), rule) == "ambiguous"
    res, score, note = settle(Market.A, "finished", [g("home", 5)], rule, True)
    assert res is Result.UNRESOLVED and "straddles" in note


def test_stoppage_and_second_half_goals_are_outside():
    assert goal_window_position(g("home", 45, extra_minute=3), STD) == "outside"
    assert goal_window_position(g("home", 3, period="2H"), STD) == "outside"


def test_cancelled_goal_ignored_and_own_goal_counted():
    goals = [g("home", 2, is_cancelled=True), g("away", 4, is_own_goal=True)]
    s = score_at_cutoff(goals, STD)
    assert (s.home, s.away) == (0, 1)
    s2 = score_at_cutoff(goals, Rule(count_own_goals=False))
    assert (s2.home, s2.away) == (0, 0)


def test_market_a_and_b_are_distinct():
    one_each = [g("home", 2), g("away", 4)]
    assert settle(Market.A, "finished", one_each, STD, True)[0] is Result.LOST
    assert settle(Market.B, "finished", one_each, STD, True)[0] is Result.WON  # 1-1 is level
    assert settle(Market.A, "finished", [], STD, True)[0] is Result.WON
    assert settle(Market.B, "finished", [], STD, True)[0] is Result.WON
    assert settle(Market.B, "finished", [g("home", 1)], STD, True)[0] is Result.LOST


def test_void_pending_and_unresolved_states():
    assert settle(Market.A, "postponed", None, STD, False)[0] is Result.VOID
    assert settle(Market.A, "cancelled", None, STD, False)[0] is Result.VOID
    assert settle(Market.A, "abandoned", [], STD, True)[0] is Result.VOID
    # Abandoned after the window was fully played -> settle on the cutoff score.
    assert settle(Market.A, "abandoned", [], STD, True, abandoned_after_seconds=1800)[0] is Result.WON
    assert settle(Market.A, "scheduled", None, STD, False)[0] is Result.PENDING
    assert settle(Market.A, "live", None, STD, False)[0] is Result.PENDING
    assert settle(Market.A, "finished", None, STD, False)[0] is Result.UNRESOLVED
    assert settle(Market.A, "finished", [], STD, False)[0] is Result.UNRESOLVED


def test_timeline_consistency():
    goals = [g("home", 10), g("away", 50, period="2H"), g("home", 20, is_cancelled=True)]
    assert timeline_consistent(goals, 1, 1)
    assert not timeline_consistent(goals, 2, 1)
    assert not timeline_consistent(goals, None, None)
    # Penalty shoot-out goals never count toward the score.
    assert timeline_consistent(goals + [g("home", 120, period="PEN")], 1, 1)
