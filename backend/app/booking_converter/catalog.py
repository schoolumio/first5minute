"""Game catalogue for the "build a ticket" flow.

The punter picks games here; the conversion engine then maps each pick onto the chosen bookmaker and asks that bookmaker for a
real booking code. The catalogue is built ONLY from sources we really have:

* ``ApiFootballCatalog`` - upcoming fixtures from the configured football data provider (the same one the scanner uses).
* ``DemoCatalog`` - fictional fixtures, only when the converter demo mode is on (never production).

Picks are a fixed menu of canonical markets (1X2, double chance, both teams to score, goals over/under 0.5-4.5). We do NOT
show prices here: a price is only meaningful at the bookmaker the punter chooses, so it appears after matching, taken from that
bookmaker. The server rebuilds every selection from this catalogue; team names and markets sent by the browser are never trusted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.booking_converter.canonical import FT
from app.booking_converter.domain import Selection
from app.booking_converter.store import ConversionStore
from app.booking_converter.store import store as default_store
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)
CACHE_SECONDS = 300          # protects the football-data request quota

# (market key, label, [(outcome key, label), ...], lines)
_MENU: list[tuple[str, str, list[tuple[str, str]], list[str | None]]] = [
    ("1X2", "Match result", [("HOME", "Home"), ("DRAW", "Draw"), ("AWAY", "Away")], [None]),
    ("DOUBLE_CHANCE", "Double chance", [("1X", "Home or draw"), ("X2", "Draw or away"), ("12", "Home or away")], [None]),
    ("BTTS", "Both teams to score", [("YES", "Yes"), ("NO", "No")], [None]),
    ("OVER_UNDER", "Total goals", [("OVER", "Over"), ("UNDER", "Under")], ["1.5", "2.5", "3.5", "0.5", "4.5"]),
]
_STD = {"1X2": ("1X2", {"HOME": "1", "DRAW": "X", "AWAY": "2"}), "DOUBLE_CHANCE": ("Double Chance", {"1X": "1X", "X2": "X2", "12": "12"}),
        "BTTS": ("Both Teams To Score", {"YES": "Yes", "NO": "No"}), "OVER_UNDER": ("Over/Under", {"OVER": "Over", "UNDER": "Under"})}


def pick_key(market: str, line: str | None, outcome: str) -> str:
    return f"{market}:{FT}:{line or '-'}:{outcome}"


@dataclass
class CatalogEvent:
    id: str
    home_team: str
    away_team: str
    start_time: datetime
    competition: str | None = None
    sport: str = "football"

    def markets(self) -> list[dict]:
        out = []
        for market, label, outcomes, lines in _MENU:
            for line in lines:
                out.append({"key": f"{market}:{line or '-'}", "label": f"{label} {line}" if line else label,
                            "picks": [{"key": pick_key(market, line, o), "label": (f"{ol} {line}" if line else ol)} for o, ol in outcomes]})
        return out

    def to_dict(self) -> dict:
        return {"id": self.id, "home_team": self.home_team, "away_team": self.away_team, "start_time": self.start_time.isoformat(),
                "competition": self.competition, "sport": self.sport}

    @classmethod
    def from_dict(cls, d: dict) -> CatalogEvent:
        return cls(d["id"], d["home_team"], d["away_team"], datetime.fromisoformat(d["start_time"]), d.get("competition"),
                   d.get("sport", "football"))


def selection_for(event: CatalogEvent, key: str) -> Selection | None:
    """Rebuild a Selection from a pick key, or None if the key is not on the menu (tampered / unknown)."""
    try:
        market, period, line, outcome = key.split(":")
    except ValueError:
        return None
    entry = next((m for m in _MENU if m[0] == market), None)
    if entry is None or period != FT or outcome not in dict(entry[2]) or (line if line != "-" else None) not in entry[3]:
        return None
    name, symbols = _STD[market]
    line_v = None if line == "-" else line
    label = f"{symbols[outcome]} {line_v}" if market == "OVER_UNDER" else symbols[outcome]
    return Selection(home_team=event.home_team, away_team=event.away_team, market_name=name, outcome=label,
                     event_id=event.id, sport=event.sport, competition=event.competition, start_time=event.start_time,
                     odds=None, specifier=line_v)


@dataclass
class Catalog:
    events: list[CatalogEvent] = field(default_factory=list)
    is_demo: bool = False
    source: str = ""
    message: str | None = None


def _demo_events() -> list[CatalogEvent]:
    from app.booking_converter.adapters.demo import DemoAlpha

    return [CatalogEvent(e.id.replace("A-", "demo:"), e.home_team, e.away_team, e.start_time, e.competition)  # type: ignore[arg-type]
            for e in DemoAlpha()._catalog(beta=False)]  # noqa: SLF001 - the demo simulator's own fictional fixtures


def _provider_events(db: Session) -> tuple[list[CatalogEvent], str | None]:
    from app.ingestion.sync import league_scope
    from app.providers.football.base import LeagueScopeError, ProviderError, ProviderPlanLimit, ProviderQuotaExceeded
    from app.providers.football.registry import get_provider

    try:
        provider = get_provider(db)
        allow = league_scope(provider)
    except LeagueScopeError as exc:
        return [], str(exc)
    except ProviderError as exc:
        return [], f"The football data provider is not configured: {exc}"
    now = datetime.now(UTC)
    events: list[CatalogEvent] = []
    message = None
    for offset in range(0, 3):
        day = (now + timedelta(days=offset)).date()
        try:
            fixtures = provider.fixtures_by_date(day)
        except (ProviderPlanLimit, ProviderQuotaExceeded) as exc:
            message = "Some days could not be loaded: your football data plan or daily request limit was reached."
            log.warning("catalog_provider_limit", error=type(exc).__name__)
            continue
        except ProviderError as exc:
            message = "The football data provider could not be reached."
            log.warning("catalog_provider_error", error=str(exc)[:120])
            continue
        for f in fixtures:
            if f.status != "scheduled" or f.kickoff_at <= now or (allow is not None and f.competition.provider_id not in allow):
                continue
            events.append(CatalogEvent(f"{provider.name}:{f.provider_id}", f.home_team.name, f.away_team.name, f.kickoff_at,
                                       f.competition.name))
    events.sort(key=lambda e: (e.start_time, e.competition or "", e.home_team))
    return events, message


def load_catalog(db: Session, store: ConversionStore | None = None) -> Catalog:
    s = get_settings()
    store = store or default_store
    if s.football_provider == "demo":
        if s.booking_converter_demo and not s.is_production:
            return Catalog(_demo_events(), True, "demo", "Fictional demo fixtures for local testing.")
        return Catalog([], False, "none", "No football data provider is configured, so there are no games to pick from yet.")
    stamp = datetime.now(UTC)
    key = f"catalog:{s.football_provider}:{stamp:%Y%m%d%H}:{stamp.minute // 5}"
    cached = store.get(key)
    if cached:
        raw = json.loads(cached)
        return Catalog([CatalogEvent.from_dict(e) for e in raw["events"]], False, s.football_provider, raw.get("message"))
    events, message = _provider_events(db)
    if events or message is None:
        store.put(key, json.dumps({"events": [e.to_dict() for e in events], "message": message}), CACHE_SECONDS)
    return Catalog(events, False, s.football_provider,
                   message or (None if events else "No upcoming matches are available from your data provider right now."))

