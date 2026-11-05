"""Bookmaker registry: the single place adapters are listed. Add a bookmaker by registering one adapter here."""

from __future__ import annotations

from app.booking_converter.adapters.base import BookmakerAdapter
from app.booking_converter.adapters.real import REAL_ADAPTERS
from app.booking_converter.errors import UnsupportedBookmaker
from app.core.config import get_settings

_EXTRA: dict[str, BookmakerAdapter] = {}      # adapters registered at runtime (used by tests and future plug-ins)


def register_adapter(adapter: BookmakerAdapter) -> None:
    _EXTRA[adapter.code] = adapter


def clear_extra_adapters() -> None:
    _EXTRA.clear()


def all_adapters() -> dict[str, BookmakerAdapter]:
    adapters: dict[str, BookmakerAdapter] = {cls.code: cls() for cls in REAL_ADAPTERS}
    if get_settings().booking_converter_demo and not get_settings().is_production:
        from app.booking_converter.adapters.demo import demo_adapters

        adapters.update({a.code: a for a in demo_adapters()})
    adapters.update(_EXTRA)
    return adapters


def get_adapter(code: str) -> BookmakerAdapter:
    adapter = all_adapters().get((code or "").strip().lower())
    if adapter is None:
        raise UnsupportedBookmaker()
    return adapter
