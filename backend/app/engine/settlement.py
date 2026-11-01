"""Five-minute settlement: establish the exact score at the cutoff.

This module is pure (no database) so it can be exhaustively unit-tested.

Timing model
------------
The settlement window is the first ``cutoff_seconds`` of first-half match
clock time (e.g. 300 -> 00:00-04:59). Providers report goal times as:

* second precision: ``second`` = elapsed seconds in the period -> exact.
* minute precision with the *ordinal* convention (football standard): minute
  ``m`` covers clock time ``[(m-1)*60, m*60)``. A goal at 04:30 is "5'".
* minute precision with the *elapsed* convention: minute ``m`` covers
  ``[m*60, (m+1)*60)``.

If a goal's time interval straddles the cutoff, the outcome is *ambiguous*
and the match is reported ``unresolved`` rather than guessed.

Stoppage-time events (``extra_minute`` set) are after the 45th/90th minute
and therefore always outside the opening window. Cancelled goals (VAR or
provider correction) never count. Own goals count for the opposing team.
Delayed kickoffs do not matter because match clock time is measured from the
actual kickoff.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.providers.football.base import ABANDONED, CANCELLED, FINAL_STATUSES, POSTPONED, SUSPENDED


class Market(StrEnum):
    A = "MARKET_A"  # no goal before cutoff (0-0)
    B = "MARKET_B"  # level score at cutoff


class Result(StrEnum):
    WON = "won"
    LOST = "lost"
    VOID = "void"
    UNRESOLVED = "unresolved"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class Rule:
    code: str = "STD_0459"
    cutoff_seconds: int = 300
    minute_convention: str = "ordinal"  # ordinal|elapsed
    count_own_goals: bool = True
    void_if_abandoned_before_cutoff: bool = True


@dataclass(frozen=True, slots=True)
class GoalTiming:
    """Minimal goal description used for settlement."""

    scoring_side: str  # "home" | "away"
    period: str
    minute: int
    extra_minute: int | None = None
    second: int | None = None
    is_cancelled: bool = False
    is_own_goal: bool = False


@dataclass(frozen=True, slots=True)
class CutoffScore:
    home: int | None
    away: int | None
    resolved: bool
    reason: str | None = None


def goal_window_position(goal: GoalTiming, rule: Rule) -> str:
    """Return "inside", "outside" or "ambiguous" relative to the window."""
    if goal.period != "1H":
        return "outside"
    if goal.extra_minute:
        return "outside"
    cutoff = rule.cutoff_seconds
    if goal.second is not None:
        return "inside" if goal.second < cutoff else "outside"
    if rule.minute_convention == "ordinal":
        start, end = (goal.minute - 1) * 60, goal.minute * 60
    else:
        start, end = goal.minute * 60, (goal.minute + 1) * 60
    start = max(start, 0)
    if end <= cutoff:
        return "inside"
    if start >= cutoff:
        return "outside"
    return "ambiguous"


def score_at_cutoff(goals: list[GoalTiming], rule: Rule) -> CutoffScore:
    home = away = 0
    for g in goals:
        if g.is_cancelled:
            continue
        if g.is_own_goal and not rule.count_own_goals:
            continue
        pos = goal_window_position(g, rule)
        if pos == "ambiguous":
            return CutoffScore(None, None, False, f"goal at minute {g.minute} straddles the cutoff")
        if pos == "inside":
            if g.scoring_side == "home":
                home += 1
            else:
                away += 1
    return CutoffScore(home, away, True)


def market_wins(market: Market | str, home: int, away: int) -> bool:
    market = Market(market)
    if market is Market.A:
        return home == 0 and away == 0
    return home == away


def settle(
    market: Market | str,
    status: str,
    goals: list[GoalTiming] | None,
    rule: Rule,
    timeline_complete: bool,
    abandoned_after_seconds: int | None = None,
) -> tuple[Result, CutoffScore | None, str | None]:
    """Settle one market for one fixture.

    ``abandoned_after_seconds`` is the match clock at abandonment when known.
    Matches abandoned after the cutoff are settled on the cutoff score (the
    window was fully played); before the cutoff (or unknown) they are void.
    """
    if status in (POSTPONED, CANCELLED):
        return Result.VOID, None, f"fixture {status}"
    if status == ABANDONED or status == SUSPENDED:
        played_window = abandoned_after_seconds is not None and abandoned_after_seconds >= rule.cutoff_seconds
        if not played_window and rule.void_if_abandoned_before_cutoff:
            return Result.VOID, None, "abandoned before or at unknown time relative to cutoff"
    elif status not in FINAL_STATUSES:
        return Result.PENDING, None, None
    if goals is None or not timeline_complete:
        return Result.UNRESOLVED, None, "event timeline missing or inconsistent with final score"
    score = score_at_cutoff(goals, rule)
    if not score.resolved:
        return Result.UNRESOLVED, score, score.reason
    assert score.home is not None and score.away is not None
    return (Result.WON if market_wins(market, score.home, score.away) else Result.LOST), score, None


def timeline_consistent(goals: list[GoalTiming], home_ft: int | None, away_ft: int | None) -> bool:
    """Goal events must reconcile exactly with the final score (excl. shoot-outs)."""
    if home_ft is None or away_ft is None:
        return False
    valid = [g for g in goals if not g.is_cancelled and g.period in ("1H", "2H")]
    h = sum(1 for g in valid if g.scoring_side == "home")
    a = sum(1 for g in valid if g.scoring_side == "away")
    return h == home_ft and a == away_ft
