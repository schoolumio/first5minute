"""Bookmaker adapter interface.

One adapter per bookmaker. An adapter wraps a LEGITIMATE integration (an official/partner API or a licensed data source) and
turns it into the converter's common types. If no such integration is connected the adapter says so (``available`` is
False) and every operation raises ``IntegrationUnavailable``: the converter never guesses, scrapes protected pages,
bypasses authentication/CAPTCHAs or invents responses.

To connect a bookmaker: subclass ``BookmakerAdapter`` (or edit its stub in ``adapters/real.py``), implement the three
operations below against the bookmaker's documented API, read credentials from environment variables, honour
``settings.booking_converter_timeout_seconds`` on every request, and flip ``can_decode`` / ``can_generate``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.booking_converter.domain import DecodedBetslip, DestEvent, EventQuery, GeneratedBooking, Pick
from app.booking_converter.errors import IntegrationUnavailable, InvalidBookingCode


@dataclass(frozen=True)
class Capabilities:
    can_decode: bool = False      # can read a booking code from this bookmaker
    can_find_events: bool = False  # can look up this bookmaker's current fixtures, markets and odds (needed as a destination)
    can_generate: bool = False    # can create a real booking code from selections


class BookmakerAdapter:
    code: str = ""
    name: str = ""
    website: str | None = None
    country: str = "NG"
    is_demo: bool = False
    capabilities: Capabilities = Capabilities()
    code_pattern: str = r"^[A-Z0-9-]{4,24}$"
    setup_note: str = ""              # shown to administrators only: what is needed to connect this bookmaker

    # --- status ----------------------------------------------------------------------------------
    def available(self) -> bool:
        """True when a working integration is connected (credentials present, connector implemented)."""
        return self.capabilities.can_decode or self.capabilities.can_find_events

    def user_message(self) -> str | None:
        return None if self.available() else "Not connected yet."

    # --- code handling ----------------------------------------------------------------------------
    def normalize_code(self, raw: str) -> str:
        code = re.sub(r"\s+", "", raw or "").upper()
        if not re.match(self.code_pattern, code):
            raise InvalidBookingCode()
        return code

    def valid_generated_code(self, code: str | None) -> bool:
        """A code returned by the bookmaker must at least look like one; anything else is treated as a failure."""
        return bool(code) and bool(re.match(r"^[A-Za-z0-9-]{3,40}$", code or ""))

    # --- operations ------------------------------------------------------------------------------
    def decode(self, code: str) -> DecodedBetslip:
        raise IntegrationUnavailable(f"{self.name} booking codes can't be read yet: no official integration is connected.")

    def find_events(self, query: EventQuery) -> list[DestEvent]:
        raise IntegrationUnavailable(f"{self.name} can't be used as a destination yet: no official integration is connected.")

    def create_booking(self, picks: list[Pick]) -> GeneratedBooking:
        raise IntegrationUnavailable(f"{self.name} doesn't offer automatic booking-code creation through a connected integration.")
