"""The bookmakers First5Minute is prepared for.

None of these has a connected integration in this codebase. First5Minute has no official API access to any of them, and
this project does not use unofficial/undocumented endpoints or scraping (they break without notice, can breach the
bookmaker's terms, and are often protected by bot detection and CAPTCHAs, which we must not bypass).

Each adapter is therefore a clearly-marked stub: the bookmaker shows in the list as "not connected yet" and conversions
involving it stop with a clear message. To enable one, implement ``decode`` / ``find_events`` / ``create_booking`` against
the bookmaker's documented partner API and set ``capabilities`` accordingly (see docs/BOOKING_CODE_CONVERTER.md).
"""

from __future__ import annotations

from app.booking_converter.adapters.base import BookmakerAdapter

_SETUP = ("Needs an official partner/API agreement with {name} that allows reading booking codes, searching fixtures/markets/odds "
          "and (optionally) creating booking codes. Then implement the three adapter methods in adapters/real.py and add the "
          "credentials as {env}_* environment variables.")


class _Pending(BookmakerAdapter):
    env = ""

    @property
    def setup_note(self) -> str:  # type: ignore[override]
        return _SETUP.format(name=self.name, env=self.env)


class Bet9jaAdapter(_Pending):
    code, name, website, env = "bet9ja", "Bet9ja", "https://www.bet9ja.com", "BET9JA"


class SportyBetAdapter(_Pending):
    code, name, website, env = "sportybet", "SportyBet", "https://www.sportybet.com/ng", "SPORTYBET"


class BetKingAdapter(_Pending):
    code, name, website, env = "betking", "BetKing", "https://www.betking.com", "BETKING"


class MSportAdapter(_Pending):
    code, name, website, env = "msport", "MSport", "https://www.msport.com/ng", "MSPORT"


class OneXBetAdapter(_Pending):
    code, name, website, env = "1xbet", "1xBet", "https://1xbet.ng", "ONEXBET"


class BetwayAdapter(_Pending):
    code, name, website, env = "betway", "Betway", "https://www.betway.com.ng", "BETWAY"


class BetPawaAdapter(_Pending):
    code, name, website, env = "betpawa", "BetPawa", "https://www.betpawa.ng", "BETPAWA"


REAL_ADAPTERS: list[type[BookmakerAdapter]] = [Bet9jaAdapter, SportyBetAdapter, BetKingAdapter, MSportAdapter, OneXBetAdapter,
                                              BetwayAdapter, BetPawaAdapter]
