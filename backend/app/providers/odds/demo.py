"""DEMO odds provider - synthetic, clearly labelled development data.

Real bookmakers rarely price five-minute markets, so local testing needs something to exercise the odds
screens. This provider fabricates odds **only for demo fixtures** and **only from the model's own current
probability plus a bookmaker margin** - so by construction no bookmaker offers value (edge is about -margin).
Everything it writes is flagged ``is_demo`` (snapshots and bookmakers), the UI shows a Demo badge, demo odds
are excluded from ROI backtests, and its sportsbook links point at example.com. It never runs for real fixtures.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Fixture, Prediction
from app.providers.odds.base import NormalizedOdds, OddsProvider

# code -> (name, margin, settlement rule code or None)
DEMO_BOOKS = {
    "demo-a": ("Demo Sportsbook A", 0.045, None),
    "demo-b": ("Demo Sportsbook B", 0.070, None),
    "demo-c": ("Demo Sportsbook C (05:00 rule)", 0.055, "STD_0500"),   # settles differently: shows the rule-mismatch warning
}
SELECTION = {"MARKET_A": "No", "MARKET_B": "Draw"}


def _unit(*parts: object) -> float:
    """Deterministic pseudo-random number in [0, 1) from the given parts."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64


class DemoOddsProvider(OddsProvider):
    name = "demo"
    fixture_provider = "demo"
    is_demo = True

    def __init__(self, db, now: datetime | None = None):
        self.db = db
        self.now = now or datetime.now(UTC)

    def bookmaker_defaults(self, code: str) -> dict:
        info = DEMO_BOOKS.get(code)
        if not info:
            return {}
        return {"is_active": True, "is_demo": True, "source": "demo", "countries": [],
                "deep_link_template": "https://example.com/demo-sportsbook/{event_ref}?utm_source=first5minute",
                "settlement_rule_code": info[2]}

    def odds_for_fixture(self, provider_fixture_id: str) -> list[NormalizedOdds]:
        if self.db is None:
            return []
        fx = self.db.scalar(select(Fixture).where(Fixture.provider == "demo", Fixture.provider_id == provider_fixture_id))
        if fx is None or not fx.is_demo:          # never fabricate odds for real fixtures
            return []
        preds = self.db.scalars(select(Prediction).where(Prediction.fixture_id == fx.id, Prediction.is_current.is_(True))).all()
        bucket = int(self.now.timestamp() // 3600)           # odds drift hourly so history has movement
        out: list[NormalizedOdds] = []
        for p in preds:
            if p.category == "excluded" or p.market_code not in SELECTION:
                continue
            for code, (name, margin, _rule) in DEMO_BOOKS.items():
                noise = (_unit(fx.id, code, p.market_code, bucket) - 0.5) * 0.06          # +/-3%
                suspended = _unit(fx.id, code, p.market_code, "susp", bucket // 6) < 0.06  # occasionally unavailable
                odds = max(1.01, round(1 / (min(p.probability, 0.995) * (1 + margin) * (1 + noise)), 2))
                out.append(NormalizedOdds(bookmaker_code=code, bookmaker_name=name, market_code=p.market_code,
                                          selection=SELECTION[p.market_code], decimal_odds=odds, is_available=not suspended,
                                          provider_updated_at=self.now, event_ref=f"demo-{fx.id}"))
        return out
