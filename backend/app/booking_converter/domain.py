"""Common internal representation of a betslip, shared by every bookmaker adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

SPORT_FOOTBALL = "football"


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    return datetime.fromisoformat(str(v)).astimezone(UTC) if "+" in str(v) or str(v).endswith("Z") else \
        datetime.fromisoformat(str(v)).replace(tzinfo=UTC)


@dataclass(frozen=True)
class Selection:
    """One leg of a source betslip, as decoded from the source bookmaker (all fields as the bookmaker reported them)."""

    home_team: str
    away_team: str
    market_name: str
    outcome: str
    event_id: str | None = None
    sport: str | None = SPORT_FOOTBALL
    competition: str | None = None
    start_time: datetime | None = None
    market_id: str | None = None
    selection_id: str | None = None
    odds: Decimal | None = None
    specifier: str | None = None        # e.g. "2.5" or "total=2.5", exactly as the bookmaker gives it
    is_live: bool = False

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id, "sport": self.sport, "competition": self.competition, "home_team": self.home_team,
            "away_team": self.away_team, "start_time": self.start_time.isoformat() if self.start_time else None,
            "market_name": self.market_name, "market_id": self.market_id, "outcome": self.outcome,
            "selection_id": self.selection_id, "odds": str(self.odds) if self.odds is not None else None,
            "specifier": self.specifier, "is_live": self.is_live,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Selection:
        return cls(home_team=d["home_team"], away_team=d["away_team"], market_name=d["market_name"], outcome=d["outcome"],
                   event_id=d.get("event_id"), sport=d.get("sport"), competition=d.get("competition"),
                   start_time=_dt(d.get("start_time")), market_id=d.get("market_id"), selection_id=d.get("selection_id"),
                   odds=_dec(d.get("odds")), specifier=d.get("specifier"), is_live=bool(d.get("is_live")))


@dataclass
class DecodedBetslip:
    bookmaker: str
    selections: list[Selection]
    is_demo: bool = False


# --- destination catalogue (what the destination bookmaker currently offers) -------------------------------------


@dataclass
class DestOutcome:
    id: str
    name: str
    odds: Decimal | None
    available: bool = True


@dataclass
class DestMarket:
    id: str
    name: str
    outcomes: list[DestOutcome]
    specifier: str | None = None


@dataclass
class DestEvent:
    id: str
    home_team: str
    away_team: str
    start_time: datetime | None
    markets: list[DestMarket] = field(default_factory=list)
    sport: str | None = SPORT_FOOTBALL
    competition: str | None = None
    is_live: bool = False


@dataclass(frozen=True)
class EventQuery:
    home_team: str
    away_team: str
    start_time: datetime | None
    sport: str | None = SPORT_FOOTBALL
    competition: str | None = None


@dataclass(frozen=True)
class Pick:
    """A fully mapped destination selection, ready to be submitted to the destination bookmaker."""

    event_id: str
    market_id: str
    outcome_id: str
    specifier: str | None = None
    expected_odds: Decimal | None = None


@dataclass
class GeneratedBooking:
    code: str
    share_url: str | None = None
    is_demo: bool = False
