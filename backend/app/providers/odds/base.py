"""Odds provider abstraction and sportbook execution adapter interface.

The MVP only *reads* odds and opens authorised sportsbook links. It never
holds funds, places bets, or asks for sportsbook credentials. The
``SportsbookExecutionAdapter`` interface exists so operators with approved
execution APIs can be integrated later, behind explicit user confirmation.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime

from app.core.config import get_settings


@dataclass(slots=True)
class NormalizedOdds:
    bookmaker_code: str
    bookmaker_name: str
    market_code: str  # MARKET_A | MARKET_B
    selection: str
    decimal_odds: float
    is_available: bool
    provider_updated_at: datetime | None = None
    event_ref: str | None = None


class OddsProvider(abc.ABC):
    name = "base"
    fixture_provider = "base"   # which football provider's fixture ids this feed understands
    is_demo = False

    @abc.abstractmethod
    def odds_for_fixture(self, provider_fixture_id: str) -> list[NormalizedOdds]: ...

    def bookmaker_defaults(self, code: str) -> dict:
        """Attributes for a bookmaker seen for the first time. Default: a pending (inactive, link-less) record
        that an administrator must review and approve before its odds are shown to users."""
        return {}


class NullOddsProvider(OddsProvider):
    """No odds source configured: returns nothing (odds are never invented)."""

    name = "none"
    fixture_provider = "none"

    def odds_for_fixture(self, provider_fixture_id: str) -> list[NormalizedOdds]:
        return []


class ApiFootballOddsProvider(OddsProvider):
    """API-Football /odds endpoint. Bet names for 5-minute markets vary by
    bookmaker; ``BET_NAME_MAP`` maps provider bet labels to our markets and is
    intentionally conservative - unknown bets are ignored, never guessed."""

    name = "api_football"
    fixture_provider = "api_football"
    BET_NAME_MAP = {
        ("goals in first 5 minutes", "no"): "MARKET_A",
        ("1x2 - 5 minutes", "draw"): "MARKET_B",
        ("result after 5 minutes", "draw"): "MARKET_B",
    }

    def __init__(self, client=None):
        from app.providers.http import ProviderHttpClient

        s = get_settings()
        if client is None:
            from app.providers.football.base import ProviderNotConfigured

            if not s.api_football_key:
                raise ProviderNotConfigured("API_FOOTBALL_KEY is not set")
            client = ProviderHttpClient("api_football_odds", s.api_football_base_url,
                                        headers={"x-apisports-key": s.api_football_key},
                                        per_minute=s.api_football_requests_per_minute)
        self.client = client

    def odds_for_fixture(self, provider_fixture_id: str) -> list[NormalizedOdds]:
        data = self.client.get("/odds", {"fixture": provider_fixture_id}, "odds_for_fixture")
        out: list[NormalizedOdds] = []
        for item in data.get("response") or []:
            updated = item.get("update")
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else None
            for bm in item.get("bookmakers") or []:
                for bet in bm.get("bets") or []:
                    for v in bet.get("values") or []:
                        market = self.BET_NAME_MAP.get(((bet.get("name") or "").lower(), str(v.get("value")).lower()))
                        if not market:
                            continue
                        try:
                            odd = float(v.get("odd"))
                        except (TypeError, ValueError):
                            continue
                        if odd <= 1.0:
                            continue
                        out.append(NormalizedOdds(
                            bookmaker_code=f"apif-{bm.get('id')}", bookmaker_name=bm.get("name") or "Unknown",
                            market_code=market, selection=str(v.get("value")), decimal_odds=odd, is_available=True,
                            provider_updated_at=ts, event_ref=provider_fixture_id,
                        ))
        return out


def get_odds_provider(db=None) -> OddsProvider:
    kind = get_settings().odds_provider
    if kind == "api_football":
        return ApiFootballOddsProvider()
    if kind == "demo":
        from app.providers.odds.demo import DemoOddsProvider

        return DemoOddsProvider(db)
    return NullOddsProvider()


class SportsbookExecutionAdapter(abc.ABC):
    """Future: operators with approved betting execution APIs.

    Implementations MUST require an explicit, per-bet user confirmation token,
    use operator-issued OAuth (never user passwords) and respect operator
    restrictions and the user's responsible-gambling limits.
    """

    @abc.abstractmethod
    def prepare_bet_slip(self, user_id: int, event_ref: str, selection: str, odds: float, stake: float) -> dict: ...

    @abc.abstractmethod
    def submit_confirmed(self, user_id: int, slip_id: str, confirmation_token: str) -> dict: ...


class ExecutionNotEnabled(Exception):
    """Raised for any attempt to place a bet. Assisted betting is link-out only in this release."""


def get_execution_adapter(bookmaker_code: str) -> SportsbookExecutionAdapter:
    """No sportsbook execution adapter is enabled. Bets are never placed by First5Minute: users open the
    operator's own site through an authorised link and place any bet themselves. A future adapter must be
    registered here only after the operator has approved an execution API, and must require a fresh,
    explicit per-bet confirmation token from the user."""
    raise ExecutionNotEnabled(f"sportsbook execution is not enabled for '{bookmaker_code}'")
