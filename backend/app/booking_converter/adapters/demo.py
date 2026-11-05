"""DEMO bookmakers - a local simulator for trying the converter without any bookmaker integration.

Enabled only with ``BOOKING_CONVERTER_DEMO=true`` and never in production (config refuses it). Teams, fixtures, odds and
codes are FICTIONAL. Generated codes start with ``DEMO-`` and are flagged ``is_demo`` so the UI labels them as not real.

Three fictional bookmakers name markets differently (so the canonical matching is genuinely exercised):
  demo_alpha - decode + fixtures + code creation      demo_beta - same, different team spellings/odds/gaps
  demo_gamma - fixtures but no code creation (shows the "recreate manually" path)

Test booking codes: DEMOALL (all convert), DEMOPART (partly), DEMOMARKET (unsupported market), DEMOGENFAIL (code creation
fails at demo_beta), DEMOWOMEN (women's fixture must not match the men's), DEMOEXPIRED (not found).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.booking_converter.adapters.base import BookmakerAdapter, Capabilities
from app.booking_converter.canonical import FT, H1, H2, M5, norm_name
from app.booking_converter.domain import (
    DecodedBetslip,
    DestEvent,
    DestMarket,
    DestOutcome,
    EventQuery,
    GeneratedBooking,
    Pick,
    Selection,
)
from app.booking_converter.errors import BookingCodeNotFound, GenerationFailed
from app.booking_converter.teams import team_similarity

ALPHA, BETA, GAMMA = "demo_alpha", "demo_beta", "demo_gamma"

# id -> (home, away, competition, hours after base, beta spelling, beta kickoff shift minutes)
_EVENTS = {
    "ev1": ("Ashford Rovers", "Calder City", "Demo Premier Division", 0, ("Ashford Rovers FC", "Calder City FC"), 0),
    "ev2": ("Glenrock Union", "Oakfield Town", "Demo Liga Norte", 2, ("Glenrock Union", "Oakfield Town FC"), 10),
    "ev3": ("Kingsport", "Lakeside", "Demo Cup", 4, ("Kingsport", "Lakeside"), 0),
    "ev3w": ("Kingsport Women", "Lakeside Women", "Demo Women's Super League", 4, ("Kingsport W", "Lakeside W"), 0),
    "ev4": ("Harbour Athletic", "Marlow Wanderers", "Demo Premier Division", 5, None, 0),            # not listed at beta
    "ev5": ("Dunmore Vale", "Eastwick", "Demo Liga Norte", 6, ("Dunmore Vale", "Eastwick FC"), 0),
    "ev6": ("Riverton", "Stonebridge", "Demo Cup", 7, ("Riverton", "Stonebridge"), 0),
    "ev7": ("Fallbridge", "Greyfield", "Demo Cup", 8, ("Fallbridge", "Greyfield"), 0),
}
# id -> list of (market, period, line, {outcome: (alpha odds, beta odds)}); beta odds None = beta does not offer it
_MARKETS = {
    "ev1": [("1X2", FT, None, {"HOME": ("1.85", "1.85"), "DRAW": ("3.40", "3.40"), "AWAY": ("4.10", "4.20")}),
            ("OU", FT, "2.5", {"OVER": ("1.90", "1.85"), "UNDER": ("1.90", "1.95")}),
            ("OU", M5, "0.5", {"OVER": ("5.20", "5.00"), "UNDER": ("1.15", "1.18")}),
            ("1X2", M5, None, {"HOME": ("4.50", "4.50"), "DRAW": ("1.20", "1.22"), "AWAY": ("6.50", "6.50")})],
    "ev2": [("BTTS", FT, None, {"YES": ("1.72", "1.72"), "NO": ("2.05", "2.05")}),
            ("OU", FT, "3.5", {"OVER": ("2.60", None), "UNDER": ("1.45", None)}),
            ("OU", FT, "2.5", {"OVER": ("1.50", "1.50"), "UNDER": ("2.45", "2.45")})],
    "ev3": [("1X2", FT, None, {"HOME": ("1.60", "1.60"), "DRAW": ("3.80", "3.80"), "AWAY": ("5.00", "5.00")}),
            ("OU", M5, "0.5", {"OVER": ("5.50", None), "UNDER": ("1.12", None)})],
    "ev3w": [("1X2", FT, None, {"HOME": ("2.00", "2.00"), "DRAW": ("3.20", "3.20"), "AWAY": ("3.50", "3.50")})],
    "ev4": [("1X2", FT, None, {"HOME": ("2.20", None), "DRAW": ("3.10", None), "AWAY": ("3.30", None)})],
    "ev5": [("1X2", FT, None, {"HOME": ("2.50", "2.50"), "DRAW": ("3.00", "3.00"), "AWAY": ("2.90", "2.90")}),
            ("OU", H2, "0.5", {"OVER": ("1.30", None), "UNDER": ("3.30", None)})],
    "ev6": [("BTTS", FT, None, {"YES": ("1.80", "1.80"), "NO": ("1.95", "1.95")})],
    "ev7": [("1X2", FT, None, {"HOME": ("2.10", "2.10"), "DRAW": ("3.20", "3.20"), "AWAY": ("3.60", "3.60")})],
}
_SUSPENDED_AT_BETA = {("ev6", "BTTS", "YES")}
_FAIL_GENERATION_AT_BETA = {"ev7"}

# booking code -> picks: (event, market, period, line, outcome); market "CORNERS" is a deliberately unsupported market
_SLIPS = {
    "DEMOALL": [("ev1", "1X2", FT, None, "HOME"), ("ev1", "OU", FT, "2.5", "OVER"), ("ev2", "BTTS", FT, None, "YES")],
    "DEMOPART": [("ev1", "1X2", FT, None, "HOME"), ("ev4", "1X2", FT, None, "HOME"), ("ev5", "OU", H2, "0.5", "OVER"),
                 ("ev6", "BTTS", FT, None, "YES"), ("ev2", "OU", FT, "3.5", "UNDER")],
    "DEMOMARKET": [("ev1", "1X2", FT, None, "HOME"), ("ev1", "CORNERS", FT, "9.5", "OVER")],
    "DEMOGENFAIL": [("ev1", "1X2", FT, None, "HOME"), ("ev7", "1X2", FT, None, "AWAY")],
    "DEMOWOMEN": [("ev3w", "1X2", FT, None, "AWAY")],
}


def _base() -> datetime:
    return (datetime.now(UTC) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)


def _market_name(style: str, market: str, period: str) -> tuple[str, bool]:
    prefix = {FT: "", H1: "1st Half - ", H2: "2nd Half - ", M5: "First 5 Minutes - " if style == "alpha" else "5 Min "}[period]
    alpha = {"1X2": "1X2", "OU": "Over/Under", "BTTS": "GG/NG", "DC": "Double Chance"}
    beta = {"1X2": "Match Result", "OU": "Total Goals", "BTTS": "Both Teams To Score", "DC": "Double Chance"}
    return prefix + (alpha if style == "alpha" else beta)[market], style == "alpha"


def _outcome_name(style: str, market: str, outcome: str, line: str | None, home: str, away: str) -> str:
    if style == "alpha":
        return {"1X2": {"HOME": "1", "DRAW": "X", "AWAY": "2"}[outcome] if market == "1X2" else "",
                "OU": f"{outcome.capitalize()} {line}", "BTTS": "GG" if outcome == "YES" else "NG"}.get(market, outcome)
    if market == "1X2":
        return {"HOME": home, "DRAW": "Draw", "AWAY": away}[outcome]
    return {"OU": outcome.capitalize(), "BTTS": "Yes" if outcome == "YES" else "No"}.get(market, outcome)


class _DemoAdapter(BookmakerAdapter):
    is_demo = True
    style = "alpha"
    code_pattern = r"^[A-Z0-9-]{4,24}$"

    def available(self) -> bool:
        return True

    def user_message(self) -> str | None:
        return "Demo bookmaker (fictional data, local testing only)."

    def decode(self, code: str) -> DecodedBetslip:
        slip = _SLIPS.get(code)
        if slip is None:
            raise BookingCodeNotFound()
        base = _base()
        out: list[Selection] = []
        for ev, market, period, line, outcome in slip:
            home, away, comp, hrs, _alt, _shift = _EVENTS[ev]
            if market == "CORNERS":
                name, label, odds = "Total Corners Over/Under", f"Over {line}", "1.95"
            else:
                name, _ = _market_name("alpha", market, period)
                label = _outcome_name("alpha", market, outcome, line, home, away)
                odds = next(o for m, p, ln, o in _MARKETS[ev] if (m, p, ln) == (market, period, line))[outcome][0]
            out.append(Selection(event_id=f"A-{ev}", sport="football", competition=comp, home_team=home, away_team=away,
                                 start_time=base + timedelta(hours=hrs), market_name=name, market_id=f"A-{market}-{period}",
                                 outcome=label, selection_id=f"A-{ev}-{market}-{outcome}", odds=Decimal(odds),
                                 specifier=line if market in ("OU", "CORNERS") else None))
        return DecodedBetslip(self.code, out, is_demo=True)


class DemoAlpha(_DemoAdapter):
    code, name, style = ALPHA, "Demo Book Alpha", "alpha"
    capabilities = Capabilities(can_decode=True, can_find_events=True, can_generate=True)

    def _render(self, beta: bool, eid: str, home: str, away: str, comp: str, start: datetime, specs: list,
                suspended: frozenset = frozenset()) -> DestEvent | None:
        style = "beta" if beta else "alpha"
        tag = style[0].upper()
        markets = []
        for market, period, line, outs in specs:
            offered = {k: v[1 if beta else 0] for k, v in outs.items()}
            if all(v is None for v in offered.values()):
                continue
            name, _ = _market_name(style, market, period)
            spec = (f"total={line}" if beta else line) if line else None
            mid = f"{tag}-{eid}-{market}-{period}-{line or 'x'}"
            markets.append(DestMarket(id=mid, name=name, specifier=spec, outcomes=[
                DestOutcome(id=f"{mid}-{k}", name=_outcome_name(style, market, k, line, home, away), odds=Decimal(v),
                            available=(eid, market, k, period) not in suspended)
                for k, v in offered.items() if v is not None]))
        return DestEvent(id=f"{tag}-{eid}", home_team=home, away_team=away, competition=comp, sport="football", start_time=start,
                         markets=markets) if markets or not beta else None

    def _catalog(self, beta: bool) -> list[DestEvent]:
        base = _base()
        events = []
        for ev, (home, away, comp, hrs, alt, shift) in _EVENTS.items():
            if beta and alt is None:
                continue
            h, a = alt if beta else (home, away)
            suspended = frozenset({(ev, m, k, FT) for (e, m, k) in _SUSPENDED_AT_BETA if e == ev}) if beta else frozenset()
            e = self._render(beta, ev, h, a, comp, base + timedelta(hours=hrs, minutes=shift if beta else 0), _MARKETS[ev], suspended)
            if e is not None:
                events.append(e)
        return events

    def _synthesised(self, q: EventQuery, beta: bool) -> DestEvent | None:
        """A fictional listing for a fixture the demo list does not contain (e.g. the demo scanner's matches).

        Deterministic from the team names: some fixtures are missing at demo_beta, some lack the five-minute markets, one is
        suspended, and prices differ slightly, so every result path can be tried. Demo simulator only.
        """
        if q.start_time is None:
            return None
        base = self._catalog(beta)
        for e in base:   # a static fixture already covers this match: do not list it twice
            if (team_similarity(q.home_team, e.home_team) >= 0.9 and team_similarity(q.away_team, e.away_team) >= 0.9
                    and e.start_time and abs(e.start_time - q.start_time) <= timedelta(minutes=30)):
                return None
        h = int(hashlib.sha256(f"{norm_name(q.home_team)}|{norm_name(q.away_team)}".encode()).hexdigest(), 16)
        if beta and h % 5 == 0:
            return None                                           # not listed at demo_beta
        home = q.home_team + (" FC" if beta else "")
        away = q.away_team + (" FC" if beta else "")
        d = Decimal(h % 60) / 100
        cut = beta and h % 2 == 0

        def pair(x: str) -> tuple[str, str]:
            v = Decimal(x) + d
            return f"{v:.2f}", f"{(v - Decimal('0.05')) if cut else v:.2f}"
        specs: list = [
            ("1X2", FT, None, {"HOME": pair("1.40"), "DRAW": pair("3.20"), "AWAY": pair("2.60")}),
            ("OU", FT, "2.5", {"OVER": pair("1.70"), "UNDER": pair("1.85")}),
            ("BTTS", FT, None, {"YES": pair("1.75"), "NO": pair("1.90")}),
        ]
        no_m5 = beta and h % 4 == 0
        if not no_m5:
            specs += [("OU", M5, "0.5", {"OVER": pair("4.80"), "UNDER": pair("1.12")}),
                      ("1X2", M5, None, {"HOME": pair("5.00"), "DRAW": pair("1.18"), "AWAY": pair("6.00")})]
        eid = "syn" + str(h % 10**6)
        suspended = frozenset({(eid, "1X2", "DRAW", M5)}) if beta and h % 7 == 0 else frozenset()
        shift = 10 if beta and h % 3 == 0 else 0
        return self._render(beta, eid, home, away, q.competition or "Demo league",
                            q.start_time + timedelta(minutes=shift), specs, suspended)

    def find_events(self, query: EventQuery) -> list[DestEvent]:
        extra = self._synthesised(query, beta=False)
        return self._catalog(beta=False) + ([extra] if extra else [])

    def create_booking(self, picks: list[Pick]) -> GeneratedBooking:
        return _demo_booking(picks, self.code, fail_events=set())


class DemoBeta(DemoAlpha):
    code, name, style = BETA, "Demo Book Beta", "beta"

    def find_events(self, query: EventQuery) -> list[DestEvent]:
        extra = self._synthesised(query, beta=True)
        return self._catalog(beta=True) + ([extra] if extra else [])

    def create_booking(self, picks: list[Pick]) -> GeneratedBooking:
        return _demo_booking(picks, self.code, fail_events=_FAIL_GENERATION_AT_BETA)


class DemoGamma(DemoAlpha):
    """Has fixtures and odds but offers no code creation: exercises the "recreate the slip manually" path."""

    code, name, style = GAMMA, "Demo Book Gamma (no code creation)", "alpha"
    capabilities = Capabilities(can_decode=True, can_find_events=True, can_generate=False)
    create_booking = BookmakerAdapter.create_booking


def _demo_booking(picks: list[Pick], bookmaker: str, fail_events: set[str]) -> GeneratedBooking:
    if not picks:
        raise GenerationFailed()
    for p in picks:
        if any(f"-{ev}" in p.event_id for ev in fail_events):
            raise GenerationFailed("The demo bookmaker refused this slip (simulated failure).")
    digest = hashlib.sha256((bookmaker + "|" + "|".join(sorted(f"{p.event_id}:{p.market_id}:{p.outcome_id}" for p in picks))
                             ).encode()).hexdigest()[:8].upper()
    return GeneratedBooking(code=f"DEMO-{digest}", share_url=None, is_demo=True)


def demo_adapters() -> list[BookmakerAdapter]:
    return [DemoAlpha(), DemoBeta(), DemoGamma()]
