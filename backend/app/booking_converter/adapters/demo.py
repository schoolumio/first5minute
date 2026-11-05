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
from app.booking_converter.canonical import FT, H1, H2
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
            ("OU", FT, "2.5", {"OVER": ("1.90", "1.85"), "UNDER": ("1.90", "1.95")})],
    "ev2": [("BTTS", FT, None, {"YES": ("1.72", "1.72"), "NO": ("2.05", "2.05")}),
            ("OU", FT, "3.5", {"OVER": ("2.60", None), "UNDER": ("1.45", None)}),
            ("OU", FT, "2.5", {"OVER": ("1.50", "1.50"), "UNDER": ("2.45", "2.45")})],
    "ev3": [("1X2", FT, None, {"HOME": ("1.60", "1.60"), "DRAW": ("3.80", "3.80"), "AWAY": ("5.00", "5.00")})],
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
    prefix = {FT: "", H1: "1st Half - ", H2: "2nd Half - "}[period]
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

    def _catalog(self, beta: bool) -> list[DestEvent]:
        base = _base()
        events = []
        for ev, (home, away, comp, hrs, alt, shift) in _EVENTS.items():
            if beta and alt is None:
                continue
            h, a = (alt if beta else (home, away))
            style = "beta" if beta else "alpha"
            markets = []
            for market, period, line, outs in _MARKETS[ev]:
                offered = {k: v[1 if beta else 0] for k, v in outs.items()}
                if all(v is None for v in offered.values()):
                    continue
                name, _ = _market_name(style, market, period)
                spec = (f"total={line}" if beta else line) if line else None
                markets.append(DestMarket(
                    id=f"{style[0].upper()}-{ev}-{market}-{period}-{line or 'x'}", name=name, specifier=spec,
                    outcomes=[DestOutcome(id=f"{style[0].upper()}-{ev}-{market}-{period}-{line or 'x'}-{k}",
                                          name=_outcome_name(style, market, k, line, h, a), odds=Decimal(v),
                                          available=not (beta and (ev, market, k) in _SUSPENDED_AT_BETA))
                              for k, v in offered.items() if v is not None]))
            events.append(DestEvent(id=f"{style[0].upper()}-{ev}", home_team=h, away_team=a, competition=comp, sport="football",
                                    start_time=base + timedelta(hours=hrs, minutes=shift if beta else 0), markets=markets))
        return events

    def find_events(self, query: EventQuery) -> list[DestEvent]:
        return self._catalog(beta=False)

    def create_booking(self, picks: list[Pick]) -> GeneratedBooking:
        return _demo_booking(picks, self.code, fail_events=set())


class DemoBeta(DemoAlpha):
    code, name, style = BETA, "Demo Book Beta", "beta"

    def find_events(self, query: EventQuery) -> list[DestEvent]:
        return self._catalog(beta=True)

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
