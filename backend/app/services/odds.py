"""Odds ingestion, freshness, comparison helpers and safe outbound links.

Principles
* Odds are append-only observations from a configured source - never invented (the demo provider is flagged).
* Unchanged odds are not re-stored except as a periodic heartbeat that proves they are still live.
* Odds older than ``max_age_minutes`` are *stale*: shown as such and never used for best price or edge.
* A bookmaker discovered in a feed is created **inactive** (pending review). Users only ever see odds from
  active, administrator-approved bookmakers permitted in their country.
* Links are built only from administrator-approved HTTPS templates; the event reference is URL-quoted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.logging import get_logger
from app.models import BettingMarket, Bookmaker, Fixture, OddsSnapshot, SettlementRule, SyncRun
from app.providers.football.base import ProviderError
from app.providers.odds.base import OddsProvider
from app.services.settings import get_setting

log = get_logger(__name__)
DEFAULT_SELECTION = {"MARKET_A": "No", "MARKET_B": "Draw"}
MAX_ODDS = 1000.0


# ------------------------------------------------------------------ bookmakers
def ensure_bookmaker(db: Session, provider: OddsProvider, code: str, name: str, cache: dict[str, Bookmaker]) -> Bookmaker:
    if code in cache:
        return cache[code]
    bm = db.scalar(select(Bookmaker).where(Bookmaker.code == code))
    if bm is None:
        d = provider.bookmaker_defaults(code)
        rule_id = None
        if d.get("settlement_rule_code"):
            rule_id = db.scalar(select(SettlementRule.id).where(SettlementRule.code == d["settlement_rule_code"]))
        bm = Bookmaker(code=code, name=name, source=d.get("source", "provider"), is_active=d.get("is_active", False),
                       is_demo=d.get("is_demo", False), countries=d.get("countries", []),
                       deep_link_template=d.get("deep_link_template"), settlement_rule_id=rule_id)
        db.add(bm)
        db.flush()
    cache[code] = bm
    return bm


def country_allowed(bm: Bookmaker, user_country: str | None) -> bool:
    allowed = [c.upper() for c in (bm.countries or [])]
    if not allowed:
        return True
    return bool(user_country) and user_country.upper() in allowed


# ------------------------------------------------------------------ queries
def latest_snapshots(db: Session, fixture_ids: list[int]) -> list[OddsSnapshot]:
    """Latest snapshot per (fixture, bookmaker, market, selection)."""
    if not fixture_ids:
        return []
    cols = (OddsSnapshot.fixture_id, OddsSnapshot.bookmaker_id, OddsSnapshot.market_id, OddsSnapshot.selection)
    return list(db.scalars(
        select(OddsSnapshot).where(OddsSnapshot.fixture_id.in_(fixture_ids))
        .distinct(*cols).order_by(*cols, OddsSnapshot.captured_at.desc(), OddsSnapshot.id.desc())))


def age_minutes(snap: OddsSnapshot, now: datetime) -> float:
    return max(0.0, (now - snap.captured_at).total_seconds() / 60)


def visible_snapshots(db: Session, fixture_ids: list[int], user_country: str | None) -> list[OddsSnapshot]:
    """Latest snapshots limited to active bookmakers permitted in the user's country."""
    return [s for s in latest_snapshots(db, fixture_ids) if s.bookmaker.is_active and country_allowed(s.bookmaker, user_country)]


def is_fresh(snap: OddsSnapshot, now: datetime, max_age_minutes: float) -> bool:
    return snap.is_available and age_minutes(snap, now) <= max_age_minutes


def best_fresh(db: Session, fixture_ids: list[int], user_country: str | None, now: datetime | None = None) -> dict[tuple[int, str], dict]:
    """Best fresh, available odds per (fixture_id, market_code) across visible bookmakers."""
    now = now or utcnow()
    max_age = float(get_setting(db, "odds.settings")["max_age_minutes"])
    best: dict[tuple[int, str], dict] = {}
    for s in visible_snapshots(db, fixture_ids, user_country):
        if not is_fresh(s, now, max_age):
            continue
        key = (s.fixture_id, s.market.code)
        cur = best.get(key)
        if cur is None or float(s.decimal_odds) > cur["decimal_odds"]:
            best[key] = {"decimal_odds": float(s.decimal_odds), "bookmaker": s.bookmaker.name, "bookmaker_code": s.bookmaker.code,
                         "captured_at": s.captured_at.isoformat(), "is_demo": s.is_demo, "n_books": 0}
    counts: dict[tuple[int, str], set[int]] = {}
    for s in visible_snapshots(db, fixture_ids, user_country):
        if is_fresh(s, now, max_age):
            counts.setdefault((s.fixture_id, s.market.code), set()).add(s.bookmaker_id)
    for k, v in best.items():
        v["n_books"] = len(counts.get(k, ()))
    return best


def best_series(db: Session, fixture_id: int, market_id: int, user_country: str | None, limit: int = 200) -> list[dict]:
    """Best available odds over time (carrying each bookmaker's last known price forward)."""
    snaps = db.scalars(select(OddsSnapshot).where(OddsSnapshot.fixture_id == fixture_id, OddsSnapshot.market_id == market_id)
                       .order_by(OddsSnapshot.captured_at, OddsSnapshot.id)).all()
    state: dict[tuple[int, str], tuple[float, bool]] = {}
    points: list[dict] = []
    for s in snaps:
        if not s.bookmaker.is_active or not country_allowed(s.bookmaker, user_country):
            continue
        state[(s.bookmaker_id, s.selection)] = (float(s.decimal_odds), s.is_available)
        live = [o for o, ok in state.values() if ok]
        point = {"t": s.captured_at.isoformat(), "best": max(live) if live else None}
        if points and points[-1]["t"] == point["t"]:
            points[-1] = point
        else:
            points.append(point)
    if len(points) > limit:
        step = len(points) / limit
        points = [points[int(i * step)] for i in range(limit)] + [points[-1]]
    return points


# ------------------------------------------------------------------ links
_PLACEHOLDER = re.compile(r"\{([^}]*)\}")


def validate_link_template(template: str) -> str:
    """Return the template if it is a safe, authorised-style deep-link template, else raise ValueError."""
    t = template.strip()
    parsed = urlparse(t.replace("{event_ref}", "x"))
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("link template must be an https:// URL")
    if "@" in parsed.netloc:
        raise ValueError("link template must not contain credentials")
    if any(ph != "event_ref" for ph in _PLACEHOLDER.findall(t)):
        raise ValueError("only the {event_ref} placeholder is allowed")
    if "{" in urlparse(t).netloc:     # judged on the ORIGINAL template, before any substitution
        raise ValueError("{event_ref} is not allowed in the host name")
    return t


def build_link(template: str | None, event_ref: str | None) -> str:
    if not template:
        raise ValueError("no authorised link is configured for this sportsbook")
    t = validate_link_template(template)
    if "{event_ref}" in t:
        if not event_ref:
            raise ValueError("this sportsbook link needs an event reference that is not available yet")
        t = t.replace("{event_ref}", quote(event_ref, safe="-_.~"))
    return t


# ------------------------------------------------------------------ sync
@dataclass
class OddsSyncStats:
    fixtures_polled: int = 0
    snapshots_added: int = 0
    marked_unavailable: int = 0
    new_bookmakers_pending: int = 0
    empty_responses: int = 0
    skipped_invalid: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def sync_odds(db: Session, provider: OddsProvider, now: datetime | None = None) -> OddsSyncStats:
    now = now or utcnow()
    cfg = get_setting(db, "odds.settings")
    stats = OddsSyncStats()
    run = SyncRun(job="odds_sync", provider=provider.name, status="running", started_at=now)
    db.add(run)
    db.flush()
    fixtures = db.scalars(
        select(Fixture).where(Fixture.status == "scheduled", Fixture.provider == provider.fixture_provider,
                              Fixture.kickoff_at > now, Fixture.kickoff_at <= now + timedelta(hours=float(cfg["lookahead_hours"])))
        .order_by(Fixture.kickoff_at).limit(int(cfg["max_fixtures_per_run"]))).all()
    markets = {m.code: m for m in db.scalars(select(BettingMarket))}
    cache: dict[str, Bookmaker] = {}
    heartbeat = timedelta(minutes=float(cfg["heartbeat_minutes"]))
    for fx in fixtures:
        stats.fixtures_polled += 1
        try:
            fetched = provider.odds_for_fixture(fx.provider_id)
        except ProviderError as exc:
            stats.errors.append(f"{fx.provider_id}: {exc}")
            continue
        if not fetched:
            stats.empty_responses += 1
            continue
        latest = {(s.bookmaker_id, s.market_id, s.selection): s for s in latest_snapshots(db, [fx.id])}
        seen: set[tuple[int, int, str]] = set()
        for o in fetched:
            mk = markets.get(o.market_code)
            if mk is None or not (1.0 < o.decimal_odds <= MAX_ODDS):
                stats.skipped_invalid += 1
                continue
            before = len(cache)
            bm = ensure_bookmaker(db, provider, o.bookmaker_code, o.bookmaker_name, cache)
            if len(cache) > before and not bm.is_active:
                stats.new_bookmakers_pending += 1
            bm.last_seen_at = now
            key = (bm.id, mk.id, o.selection)
            seen.add(key)
            prev = latest.get(key)
            odds = round(float(o.decimal_odds), 3)
            changed = prev is None or float(prev.decimal_odds) != odds or prev.is_available != o.is_available
            due = prev is not None and (now - prev.captured_at) >= heartbeat
            if changed or due:
                db.add(OddsSnapshot(fixture_id=fx.id, bookmaker_id=bm.id, market_id=mk.id, selection=o.selection, decimal_odds=odds,
                                    is_available=o.is_available, source_provider=provider.name, is_demo=provider.is_demo,
                                    event_ref=o.event_ref, captured_at=now, provider_updated_at=o.provider_updated_at))
                stats.snapshots_added += 1
        # A non-empty response that omits a previously available price means it was withdrawn.
        for key, prev in latest.items():
            if key not in seen and prev.is_available:
                db.add(OddsSnapshot(fixture_id=fx.id, bookmaker_id=prev.bookmaker_id, market_id=prev.market_id, selection=prev.selection,
                                    decimal_odds=prev.decimal_odds, is_available=False, source_provider=provider.name,
                                    is_demo=prev.is_demo, event_ref=prev.event_ref, captured_at=now))
                stats.marked_unavailable += 1
        db.flush()
    run.status = "success" if not stats.errors else "partial"
    run.finished_at, run.stats = utcnow(), stats.as_dict()
    db.flush()
    log.info("odds_sync_complete", **{k: v for k, v in stats.as_dict().items() if k != "errors"})
    return stats


# ------------------------------------------------------------------ manual import
def import_odds(db: Session, rows: list[dict], now: datetime | None = None) -> dict:
    """Insert odds supplied by an administrator from an authorised source (e.g. a licensed CSV/JSON feed)."""
    now = now or utcnow()
    markets = {m.code: m for m in db.scalars(select(BettingMarket))}
    out = {"inserted": 0, "duplicates": 0, "new_bookmakers_pending": 0, "errors": []}
    books: dict[str, Bookmaker] = {}
    for i, r in enumerate(rows):
        fx = db.get(Fixture, r["fixture_id"])
        mk = markets.get(r["market"])
        if fx is None or mk is None:
            out["errors"].append(f"row {i}: unknown fixture or market")
            continue
        captured = r.get("captured_at") or now
        if captured.tzinfo is None:
            out["errors"].append(f"row {i}: captured_at must include a timezone")
            continue
        if captured >= fx.kickoff_at:
            out["errors"].append(f"row {i}: odds captured at/after kick-off are not accepted")
            continue
        code = r["bookmaker_code"]
        bm = books.get(code) or db.scalar(select(Bookmaker).where(Bookmaker.code == code))
        if bm is None:
            bm = Bookmaker(code=code, name=r.get("bookmaker_name") or code, source="manual", is_active=False)
            db.add(bm)
            db.flush()
            out["new_bookmakers_pending"] += 1
        books[code] = bm
        selection = r.get("selection") or DEFAULT_SELECTION[r["market"]]
        exists = db.scalar(select(OddsSnapshot.id).where(
            OddsSnapshot.fixture_id == fx.id, OddsSnapshot.bookmaker_id == bm.id, OddsSnapshot.market_id == mk.id,
            OddsSnapshot.selection == selection, OddsSnapshot.captured_at == captured))
        if exists:
            out["duplicates"] += 1
            continue
        db.add(OddsSnapshot(fixture_id=fx.id, bookmaker_id=bm.id, market_id=mk.id, selection=selection,
                            decimal_odds=round(float(r["decimal_odds"]), 3), is_available=r.get("is_available", True),
                            source_provider="manual_import", is_demo=False, event_ref=r.get("event_ref"), captured_at=captured))
        out["inserted"] += 1
    db.flush()
    out["errors"] = out["errors"][:50]
    return out
