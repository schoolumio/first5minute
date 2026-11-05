"""Virtual "source" for tickets a punter builds on First5Minute (there is no bookmaker code to decode)."""

from __future__ import annotations

from app.booking_converter.adapters.base import BookmakerAdapter

TICKET_SOURCE = "first5minute"


class TicketSource(BookmakerAdapter):
    code, name, hidden = TICKET_SOURCE, "First5Minute ticket", True

    def available(self) -> bool:
        return True
