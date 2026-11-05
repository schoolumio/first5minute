"""Event and selection matching.

Rules (all deliberate):
* An event matches only when BOTH teams match, the kick-off times agree (within 30 minutes) and the sport agrees.
* Two plausible candidates -> "ambiguous", never a guess. Reversed home/away -> "teams_reversed", never auto-swapped.
* A selection maps only to a destination outcome with the IDENTICAL canonical market, period, goals line and outcome.
  No nearest-line, no "similar" market, no substitute outcome.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.booking_converter.canonical import Canon, canonicalize, norm_name
from app.booking_converter.domain import DestEvent, DestMarket, DestOutcome, EventQuery, Pick, Selection
from app.booking_converter.errors import ConverterError, IntegrationUnavailable, UpstreamError
from app.booking_converter.teams import team_similarity
from app.core.logging import get_logger

log = get_logger(__name__)

MATCHED, ODDS_CHANGED, UNMATCHED, UNAVAILABLE = "matched", "odds_changed", "unmatched", "unavailable"
TEAM_MATCH_MIN = 0.90
SUBSET_MIN = 0.88
TIME_TOLERANCE = timedelta(minutes=30)
STRONG_TIME = timedelta(minutes=5)
AMBIGUITY_MARGIN = 0.03

REASONS = {
    "no_fixture": "No matching fixture was found at the destination bookmaker.",
    "ambiguous_fixture": "More than one destination fixture looked like a match, so none was chosen.",
    "teams_reversed": "The destination lists the teams the other way round, so the pick cannot be copied safely.",
    "time_mismatch": "A fixture with the same teams exists but at a different time.",
    "start_time_missing": "The kick-off time is missing, so the fixture cannot be matched safely.",
    "sport_unsupported": "Only football selections can be converted.",
    "market_unsupported": "This market type is not supported by the converter yet.",
    "market_unavailable": "The destination bookmaker does not offer this market for the fixture.",
    "line_unavailable": "The destination bookmaker does not offer this goals line for the fixture.",
    "outcome_unavailable": "The destination bookmaker does not offer this outcome.",
    "ambiguous_market": "The destination lists this market more than once, so none was chosen.",
    "suspended": "This selection is currently suspended at the destination bookmaker.",
    "event_started": "The destination fixture has already started.",
    "lookup_failed": "The destination bookmaker could not be reached for this fixture.",
    "lookup_timeout": "Matching ran out of time before this fixture was checked.",
}


@dataclass
class EventMatch:
    event: DestEvent | None
    reason: str | None = None
    confidence: str | None = None        # "high" | "medium"


@dataclass
class SelectionResult:
    index: int
    source: Selection
    status: str
    reason_code: str | None = None
    reason: str | None = None
    canon: Canon | None = None
    dest_event: DestEvent | None = None
    dest_market: DestMarket | None = None
    dest_outcome: DestOutcome | None = None
    confidence: str | None = None
    pick: Pick | None = None

    @property
    def matched(self) -> bool:
        return self.status in (MATCHED, ODDS_CHANGED)

    @property
    def odds_change(self) -> str | None:
        if not self.matched or self.source.odds is None or self.dest_outcome is None or self.dest_outcome.odds is None:
            return None
        a, b = _q(self.source.odds), _q(self.dest_outcome.odds)
        return "same" if a == b else ("up" if b > a else "down")


def _q(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"))


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def match_event(sel: Selection, candidates: list[DestEvent]) -> EventMatch:
    """Pick the single destination event that is the same fixture as ``sel``'s, or explain why none is."""
    if sel.start_time is None:
        return EventMatch(None, "start_time_missing")
    start = _aware(sel.start_time)
    passing: list[tuple[float, timedelta, DestEvent]] = []
    saw_reversed = saw_time_only = False
    for c in candidates:
        if sel.sport and c.sport and norm_name(sel.sport) != norm_name(c.sport):
            continue
        sh, sa = team_similarity(sel.home_team, c.home_team), team_similarity(sel.away_team, c.away_team)
        lo, hi = min(sh, sa), max(sh, sa)
        names_ok = lo >= TEAM_MATCH_MIN
        subset_ok = SUBSET_MIN <= lo < TEAM_MATCH_MIN and hi >= 0.97
        if not (names_ok or subset_ok):
            rs = min(team_similarity(sel.home_team, c.away_team), team_similarity(sel.away_team, c.home_team))
            saw_reversed = saw_reversed or rs >= TEAM_MATCH_MIN
            continue
        cstart = _aware(c.start_time)
        if cstart is None:
            continue
        diff = abs(cstart - start)
        if diff > TIME_TOLERANCE:
            saw_time_only = True
            continue
        if subset_ok and not names_ok and diff > STRONG_TIME:
            saw_time_only = True            # partial names need a near-exact kick-off to count
            continue
        passing.append((lo, diff, c))
    if not passing:
        if saw_reversed:
            return EventMatch(None, "teams_reversed")
        return EventMatch(None, "time_mismatch" if saw_time_only else "no_fixture")
    passing.sort(key=lambda t: (-t[0], t[1]))
    if len(passing) > 1 and passing[0][0] - passing[1][0] < AMBIGUITY_MARGIN and passing[0][2].id != passing[1][2].id:
        return EventMatch(None, "ambiguous_fixture")
    lo, diff, best = passing[0]
    confidence = "high" if lo >= 0.97 and diff <= STRONG_TIME else "medium"
    return EventMatch(best, None, confidence)


def _index_event(event: DestEvent) -> dict[Canon, list[tuple[DestMarket, DestOutcome]]]:
    idx: dict[Canon, list[tuple[DestMarket, DestOutcome]]] = defaultdict(list)
    for m in event.markets:
        for o in m.outcomes:
            res = canonicalize(m.name, o.name, m.specifier, event.home_team, event.away_team)
            if res.canon is not None:
                idx[res.canon].append((m, o))
    return idx


def map_selection(index: int, sel: Selection, event: DestEvent, confidence: str | None, now: datetime) -> SelectionResult:
    """Map one source selection onto the already-matched destination event."""
    res = canonicalize(sel.market_name, sel.outcome, sel.specifier, sel.home_team, sel.away_team)
    if res.canon is None:
        return SelectionResult(index, sel, UNMATCHED, "market_unsupported", res.reason or REASONS["market_unsupported"])
    canon = res.canon
    base = {"canon": canon, "dest_event": event, "confidence": confidence}
    if event.is_live or (event.start_time and _aware(event.start_time) <= now):
        return SelectionResult(index, sel, UNAVAILABLE, "event_started", REASONS["event_started"], **base)
    idx = _index_event(event)
    hits = idx.get(canon, [])
    distinct = {(m.id, o.id) for m, o in hits}
    if len(distinct) > 1:
        return SelectionResult(index, sel, UNMATCHED, "ambiguous_market", REASONS["ambiguous_market"], **base)
    if not hits:
        same_market = [c for c in idx if c.market_key() == canon.market_key()]
        if not same_market:
            return SelectionResult(index, sel, UNAVAILABLE, "market_unavailable", REASONS["market_unavailable"], **base)
        if canon.line is not None and all(c.line != canon.line for c in same_market):
            return SelectionResult(index, sel, UNAVAILABLE, "line_unavailable", REASONS["line_unavailable"], **base)
        return SelectionResult(index, sel, UNAVAILABLE, "outcome_unavailable", REASONS["outcome_unavailable"], **base)
    market, outcome = hits[0]
    if not outcome.available or outcome.odds is None:
        return SelectionResult(index, sel, UNAVAILABLE, "suspended", REASONS["suspended"], dest_market=market,
                               dest_outcome=outcome, **base)
    pick = Pick(event_id=event.id, market_id=market.id, outcome_id=outcome.id, specifier=market.specifier,
                expected_odds=outcome.odds)
    status = MATCHED
    if sel.odds is not None and _q(sel.odds) != _q(outcome.odds):
        status = ODDS_CHANGED
    return SelectionResult(index, sel, status, None, None, dest_market=market, dest_outcome=outcome, pick=pick, **base)


def _event_key(sel: Selection) -> tuple:
    start = _aware(sel.start_time)
    return (norm_name(sel.home_team), norm_name(sel.away_team), start.replace(second=0, microsecond=0) if start else None,
            norm_name(sel.sport or ""))


def match_betslip(selections: list[Selection], find_events, deadline_seconds: float = 45.0,
                  now: datetime | None = None) -> list[SelectionResult]:
    """Match every selection. ``find_events(EventQuery) -> list[DestEvent]`` is the destination adapter's lookup.

    Every input selection yields exactly one result: nothing is dropped silently. If the destination integration itself is
    unavailable the error propagates (the whole conversion cannot proceed); per-fixture lookup failures become
    "lookup_failed" results for that fixture's selections only.
    """
    now = now or datetime.now(UTC)
    started = time.monotonic()
    groups: dict[tuple, list[int]] = {}
    for i, s in enumerate(selections):
        groups.setdefault(_event_key(s), []).append(i)
    results: dict[int, SelectionResult] = {}
    for _key, idxs in groups.items():
        first = selections[idxs[0]]
        if first.sport and norm_name(first.sport) not in ("football", "soccer"):
            for i in idxs:
                results[i] = SelectionResult(i, selections[i], UNMATCHED, "sport_unsupported", REASONS["sport_unsupported"])
            continue
        if time.monotonic() - started > deadline_seconds:
            for i in idxs:
                results[i] = SelectionResult(i, selections[i], UNAVAILABLE, "lookup_timeout", REASONS["lookup_timeout"])
            continue
        if first.start_time is None:
            for i in idxs:
                results[i] = SelectionResult(i, selections[i], UNMATCHED, "start_time_missing", REASONS["start_time_missing"])
            continue
        try:
            candidates = find_events(EventQuery(first.home_team, first.away_team, first.start_time, first.sport,
                                                first.competition))
        except IntegrationUnavailable:
            raise
        except UpstreamError as exc:
            log.warning("destination_lookup_failed", error=exc.code)
            for i in idxs:
                results[i] = SelectionResult(i, selections[i], UNAVAILABLE, "lookup_failed", REASONS["lookup_failed"])
            continue
        except ConverterError:
            raise
        em = match_event(first, candidates)
        for i in idxs:
            if em.event is None:
                code = em.reason or "no_fixture"
                results[i] = SelectionResult(i, selections[i], UNMATCHED, code, REASONS[code])
            else:
                results[i] = map_selection(i, selections[i], em.event, em.confidence, now)
    return [results[i] for i in range(len(selections))]


def reason_text(code: str | None) -> str | None:
    return REASONS.get(code) if code else None
