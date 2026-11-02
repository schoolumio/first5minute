"""Select the configured football provider. New providers register here only."""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.providers.football.base import FootballDataProvider

PROVIDERS = {
    "api_football": "app.providers.football.api_football:ApiFootballProvider",
    "sportmonks": "app.providers.football.sportmonks:SportmonksProvider",
    "demo": "app.providers.football.demo:DemoFootballProvider",
}


def demo_anchor(db: Session | None) -> date:
    if db is not None:
        from app.services.settings import get_setting

        anchor = get_setting(db, "demo.anchor").get("date")
        if anchor:
            return date.fromisoformat(anchor)
    return datetime.now(UTC).date()


def get_provider(db: Session | None = None, name: str | None = None) -> FootballDataProvider:
    name = name or get_settings().football_provider
    if name == "demo":
        from app.providers.football.demo import DemoFootballProvider

        return DemoFootballProvider(anchor=demo_anchor(db))
    target = PROVIDERS.get(name)
    if target is None:
        raise ValueError(f"unknown football provider {name!r}")
    module, cls = target.split(":")
    mod = __import__(module, fromlist=[cls])
    return getattr(mod, cls)()


def league_scope_status() -> dict:
    s = get_settings()
    return {"league_ids": [i.strip() for i in s.football_league_ids if i.strip()], "allow_all": s.football_allow_all_leagues,
            "required": s.football_provider != "demo"}


def provider_status() -> list[dict]:
    """Configuration status for every known provider (never exposes secrets)."""
    s = get_settings()
    return [
        {"name": "api_football", "label": "API-Football", "configured": bool(s.api_football_key),
         "active": s.football_provider == "api_football", "env": "API_FOOTBALL_KEY"},
        {"name": "sportmonks", "label": "Sportmonks", "configured": bool(s.sportmonks_token),
         "active": s.football_provider == "sportmonks", "env": "SPORTMONKS_TOKEN"},
        {"name": "demo", "label": "Demo data (synthetic)", "configured": True,
         "active": s.football_provider == "demo", "env": None},
    ]
