"""Odds comparison (Pro+). Shows only odds recorded from configured odds providers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_feature
from app.core.config import get_settings
from app.core.database import get_db, utcnow
from app.models import Fixture, OddsSnapshot, User

router = APIRouter(prefix="/odds", tags=["odds"])


def deep_link(template: str | None, event_ref: str | None) -> str | None:
    if not template:
        return None
    if "{event_ref}" in template:
        return template.replace("{event_ref}", event_ref or "") if event_ref else None
    return template


@router.get("/{fixture_id}")
def fixture_odds(fixture_id: int, user: User = Depends(require_feature("odds_comparison")), db: Session = Depends(get_db)) -> dict:
    fx = db.get(Fixture, fixture_id)
    if fx is None:
        raise HTTPException(404, "Fixture not found")
    snaps = db.scalars(select(OddsSnapshot).where(OddsSnapshot.fixture_id == fx.id)
                       .order_by(OddsSnapshot.captured_at.desc())).all()
    excluded = user.rg_self_excluded_until is not None and user.rg_self_excluded_until > utcnow()
    latest: dict[tuple[int, str], OddsSnapshot] = {}
    history: dict[str, list] = {}
    for s in snaps:
        latest.setdefault((s.bookmaker_id, s.market.code), s)
        history.setdefault(f"{s.bookmaker.code}:{s.market.code}", []).append(
            {"captured_at": s.captured_at.isoformat(), "decimal_odds": float(s.decimal_odds)})
    rows = [
        {
            "bookmaker": {"id": s.bookmaker.id, "code": s.bookmaker.code, "name": s.bookmaker.name},
            "market": s.market.code,
            "selection": s.selection,
            "decimal_odds": float(s.decimal_odds),
            "implied_probability": round(1 / float(s.decimal_odds), 4),
            "is_available": s.is_available and s.bookmaker.is_active,
            "last_updated": (s.provider_updated_at or s.captured_at).isoformat(),
            "link": None if excluded else deep_link(s.bookmaker.deep_link_template, s.event_ref),
        }
        for s in latest.values()
    ]
    rows.sort(key=lambda r: (r["market"], -r["decimal_odds"]))
    provider = get_settings().odds_provider
    return {
        "fixture_id": fx.id,
        "odds_provider": provider,
        "provider_configured": provider != "none",
        "odds": rows,
        "history": history,
        "self_excluded": excluded,
        "message": None if rows else (
            "No odds available. No odds provider is configured." if provider == "none"
            else "No supported bookmaker currently prices this market for this fixture."
        ),
        "notice": "18+. Odds can change at any time. Project Five does not accept bets or hold funds.",
    }
