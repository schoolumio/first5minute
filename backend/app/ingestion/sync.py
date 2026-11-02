"""Synchronisation jobs: pull fixtures/events from the provider into the DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import utcnow
from app.core.logging import get_logger
from app.ingestion.service import Ingestor, IngestStats
from app.models import Fixture, SyncRun
from app.providers.football.base import (
    FINAL_STATUSES,
    FootballDataProvider,
    LeagueScopeError,
    NormalizedFixture,
    ProviderError,
    ProviderPlanLimit,
    ProviderQuotaExceeded,
)
from app.services.settings import default_rule_row, rule_from_row

log = get_logger(__name__)


def _ingestor(db: Session, provider: FootballDataProvider) -> Ingestor:
    return Ingestor(db, provider.name, provider.is_demo, rule_from_row(default_rule_row(db)))


def league_scope(provider: FootballDataProvider) -> set[str] | None:
    """Provider league ids to ingest. ``None`` = no filtering (demo data, or an explicit opt-in to everything).

    Real providers REQUIRE an allowlist: without one the sync would pull every competition worldwide and burn the
    API quota within minutes."""
    s = get_settings()
    if provider.is_demo:
        return None
    ids = {i.strip() for i in s.football_league_ids if i.strip()}
    if ids:
        return ids
    if s.football_allow_all_leagues:
        return None
    raise LeagueScopeError(
        "No league allowlist configured. Set FOOTBALL_LEAGUE_IDS in .env (comma-separated provider league ids, e.g. 39,140) - "
        "find ids with: python -m app.cli leagues --search premier. "
        "(FOOTBALL_ALLOW_ALL_LEAGUES=true syncs every competition worldwide: very high request volume.)")


def sync_days(db: Session, provider: FootballDataProvider, days: list[date], with_events_for_final: bool = True,
              league_ids: set[str] | None = None) -> IngestStats:
    """Ingest fixtures for each day (allowlisted leagues only) and fetch timelines for final fixtures in bulk.

    * Each fixture is ingested in its own savepoint so one bad record cannot abort the run.
    * When the provider's quota is exhausted the run stops cleanly (``stats.quota_exhausted``); everything fetched so far
      is kept, and timeline-less fixtures are picked up by the next run.
    """
    allow = league_ids if league_ids is not None else league_scope(provider)
    run = SyncRun(job="sync_fixtures", provider=provider.name, status="running")
    db.add(run)
    db.commit()
    ing = _ingestor(db, provider)
    try:
        queue = list(days)
        window: tuple[date, date] | None = None
        while queue:
            day = queue.pop(0)
            if window and not (window[0] <= day <= window[1]):
                ing.stats.days_outside_plan += 1          # known to be outside the plan: no request is spent on it
                continue
            try:
                fixtures = provider.fixtures_by_date(day)
            except ProviderQuotaExceeded as exc:
                ing.stats.quota_exhausted = True
                ing.stats.errors.append(str(exc))
                break
            except ProviderPlanLimit as exc:
                if exc.window and window is None:
                    # e.g. the free plan only serves yesterday..tomorrow: remember the window, skip this day and
                    # every other day outside it, and carry on with the days the plan does allow.
                    window = exc.window
                    ing.stats.days_outside_plan += 1
                    log.info("plan_date_window", first=str(window[0]), last=str(window[1]))
                    continue
                ing.stats.plan_limited = True
                ing.stats.errors.append(str(exc))
                break
            kept = [nf for nf in fixtures if allow is None or nf.competition.provider_id in allow]
            ing.stats.filtered_out += len(fixtures) - len(kept)
            detailed: dict[str, NormalizedFixture] = {}
            if with_events_for_final:
                need = [nf.provider_id for nf in kept if nf.status in FINAL_STATUSES or nf.status == "abandoned"]
                pos = 0
                while pos < len(need):
                    size = max(1, provider.events_batch_size)       # re-read each time: a provider may fall back to 1
                    chunk, pos = need[pos:pos + size], pos + size
                    try:
                        for d in provider.fixtures_with_events(chunk):
                            detailed[d.provider_id] = d
                    except ProviderQuotaExceeded as exc:
                        for d in exc.partial:
                            detailed[d.provider_id] = d
                        ing.stats.quota_exhausted = True
                        ing.stats.errors.append(str(exc))
                        break
                    except ProviderPlanLimit as exc:
                        ing.stats.plan_limited = True
                        ing.stats.errors.append(str(exc))
                        break
                    except ProviderError as exc:
                        ing.stats.errors.append(f"events {','.join(chunk[:3])}...: {exc}")
            for nf in kept:
                try:
                    with db.begin_nested():
                        ing.ingest_fixture(detailed.get(nf.provider_id, nf))
                except (ProviderError, ValueError) as exc:
                    ing.stats.errors.append(f"{nf.provider_id}: {exc}")
            db.commit()
            if ing.stats.quota_exhausted or ing.stats.plan_limited:
                break
        stopped = ing.stats.quota_exhausted or ing.stats.plan_limited
        run.status = "quota_hit" if stopped else ("success" if not ing.stats.errors else "partial")
    except ProviderError as exc:
        db.rollback()
        run = db.merge(run)
        run.status, run.error = "failed", str(exc)
        log.error("sync_failed", provider=provider.name, error=str(exc))
    run.finished_at, run.stats = utcnow(), {**ing.stats.as_dict(), "errors": ing.stats.errors[:50]}
    db.commit()
    return ing.stats


def refresh_pending_results(db: Session, provider: FootballDataProvider, lookback_hours: int = 72) -> IngestStats:
    """Re-fetch recently kicked-off fixtures that are not yet final or lack events."""
    now = utcnow()
    fixtures = db.scalars(
        select(Fixture).where(
            Fixture.provider == provider.name,
            Fixture.kickoff_at <= now,
            Fixture.kickoff_at >= now - timedelta(hours=lookback_hours),
            (Fixture.status.notin_(list(FINAL_STATUSES))) | (Fixture.timeline_status != "complete"),
        )
    ).all()
    ing = _ingestor(db, provider)
    for fx in fixtures:
        try:
            with db.begin_nested():
                ing.ingest_fixture(provider.fixture_with_events(fx.provider_id))
        except (ProviderError, ValueError) as exc:
            ing.stats.errors.append(f"{fx.provider_id}: {exc}")
    db.commit()
    return ing.stats


def sync_window(db: Session, provider: FootballDataProvider, past_days: int, future_days: int) -> IngestStats:
    today = datetime.now(UTC).date()
    # Nearest to today first: plans with a short date window (free: yesterday..tomorrow) serve those days, and a
    # refused day teaches the sync the window so it can skip the rest without spending requests.
    offsets = sorted(range(-past_days, future_days + 1), key=lambda d: (abs(d), -d))
    days = [today + timedelta(days=d) for d in offsets]
    return sync_days(db, provider, days)


def backfill_history(db: Session, provider: FootballDataProvider, days: int, chunk_days: int = 7, force: bool = False,
                     progress=None) -> dict:
    """Pull ``days`` of past fixtures (with event timelines for final matches), oldest first, in chunks.

    Days that already have fully synchronised final fixtures from this provider are skipped unless ``force``
    (so an interrupted backfill can simply be re-run). Provider rate limits apply via the adapter's client.
    """
    today = datetime.now(UTC).date()
    all_days = [today - timedelta(days=d) for d in range(days, 0, -1)]
    todo: list[date] = []
    skipped = 0
    for day in all_days:
        start = datetime.combine(day, datetime.min.time(), UTC)
        day_filter = (Fixture.provider == provider.name, Fixture.kickoff_at >= start, Fixture.kickoff_at < start + timedelta(days=1),
                      Fixture.status.in_(list(FINAL_STATUSES)))
        finals = db.scalar(select(func.count(Fixture.id)).where(*day_filter)) or 0
        unsynced = db.scalar(select(func.count(Fixture.id)).where(*day_filter, Fixture.events_synced_at.is_(None))) or 0
        if finals and not unsynced and not force:        # a day interrupted by a quota stop is retried, not skipped
            skipped += 1
        else:
            todo.append(day)
    totals = {"days_requested": days, "days_skipped": skipped, "days_synced": 0, "fixtures_created": 0, "fixtures_updated": 0,
              "events_replaced": 0, "filtered_out": 0, "stopped_reason": None, "errors": []}
    for i in range(0, len(todo), chunk_days):
        chunk = todo[i:i + chunk_days]
        stats = sync_days(db, provider, chunk)
        totals["days_synced"] += len(chunk)
        for k in ("fixtures_created", "fixtures_updated", "events_replaced", "filtered_out"):
            totals[k] += getattr(stats, k)
        totals["errors"].extend(stats.errors[:10])
        if progress:
            progress(chunk[-1], totals)
        if stats.plan_limited:
            totals["stopped_reason"] = stats.errors[0] if stats.errors else "your provider plan does not include this date range"
            break
        if stats.quota_exhausted:
            totals["stopped_reason"] = ("provider request limit reached - progress is saved; run the same command again "
                                        "after your quota resets (it resumes where it stopped)")
            break
    totals["errors"] = totals["errors"][:50]
    return totals


def _ingest_detail(db: Session, ing: Ingestor, d: NormalizedFixture, out: dict) -> None:
    try:
        with db.begin_nested():
            ing.ingest_fixture(d)
        out["timelines_fetched"] += 1
    except (ProviderError, ValueError) as exc:
        out["errors"].append(f"{d.provider_id}: {exc}")


def _quota_message(db: Session, provider: FootballDataProvider, finals: list[str]) -> str:
    missing = db.scalar(select(func.count(Fixture.id)).where(
        Fixture.provider == provider.name, Fixture.provider_id.in_(finals or [""]), Fixture.timeline_status != "complete")) or 0
    msg = "provider request limit reached - progress is saved; run the same command again after your quota resets (it resumes)."
    try:
        limit = (provider.health_check().get("requests") or {}).get("limit_day")
    except ProviderError:
        limit = None
    if missing and limit:
        per_day = max(1, int(limit) - 5)
        msg += f" {missing} timelines still to download: about {-(-missing // per_day)} more daily run(s) at {limit} requests/day."
    return msg


def sync_league_season(db: Session, provider: FootballDataProvider, league_id: str, season: int, progress=None) -> dict:
    """Download one whole league-season: ONE request for the fixture list, then match timelines in bulk (20 per request).

    A 20-team league-season is roughly 1 + 19 requests. Progress is committed after every bulk batch, and fixtures that already
    have a reconciled timeline are skipped, so an interrupted run (quota, network, plan limit) simply resumes when re-run.
    """
    run = SyncRun(job="sync_season", provider=provider.name, status="running")
    db.add(run)
    db.commit()
    ing = _ingestor(db, provider)
    out: dict = {"league": league_id, "season": season, "fixtures": 0, "finished": 0, "timelines_fetched": 0, "timelines_missing": 0,
                 "stopped_reason": None, "errors": []}
    try:
        fixtures = [nf for nf in provider.fixtures_by_league_season(league_id, season)]
        out["fixtures"] = len(fixtures)
        for nf in fixtures:           # statuses, scores and schedule first (cheap, no extra requests)
            try:
                with db.begin_nested():
                    ing.ingest_fixture(nf)
            except (ProviderError, ValueError) as exc:
                out["errors"].append(f"{nf.provider_id}: {exc}")
        db.commit()
        ordered = sorted((nf for nf in fixtures if nf.status in FINAL_STATUSES or nf.status == "abandoned"), key=lambda n: n.kickoff_at)
        finals = [nf.provider_id for nf in ordered]                 # oldest first: partial downloads are still usable chronologically
        out["finished"] = len(finals)
        done = set(db.scalars(select(Fixture.provider_id).where(
            Fixture.provider == provider.name, Fixture.provider_id.in_(finals or [""]), Fixture.timeline_status == "complete")))
        need = [i for i in finals if i not in done]
        pos = 0
        while pos < len(need):
            size = max(1, provider.events_batch_size)               # becomes 1 if the plan refuses bulk requests
            chunk, pos = need[pos:pos + size], pos + size
            try:
                for d in provider.fixtures_with_events(chunk):
                    _ingest_detail(db, ing, d, out)
                db.commit()
            except ProviderQuotaExceeded as exc:
                for d in exc.partial:
                    _ingest_detail(db, ing, d, out)
                db.commit()
                out["stopped_reason"] = _quota_message(db, provider, finals)
                break
            except ProviderPlanLimit as exc:
                out["stopped_reason"] = str(exc)
                break
            except ProviderError as exc:
                out["errors"].append(f"events {chunk[0]}...: {exc}")
            if progress:
                progress(out)
        out["timelines_missing"] = db.scalar(select(func.count(Fixture.id)).where(
            Fixture.provider == provider.name, Fixture.provider_id.in_(finals or [""]), Fixture.timeline_status != "complete")) or 0
        run.status = "quota_hit" if out["stopped_reason"] else ("success" if not out["errors"] else "partial")
    except ProviderPlanLimit as exc:
        db.rollback()
        run = db.merge(run)
        run.status, run.error = "failed", str(exc)
        out["stopped_reason"] = str(exc)
    except ProviderQuotaExceeded:
        db.rollback()
        run = db.merge(run)
        run.status = "quota_hit"
        out["stopped_reason"] = "provider request limit reached - run the same command again after your quota resets"
    run.finished_at, run.stats = utcnow(), {**out, "errors": out["errors"][:50]}
    db.commit()
    out["errors"] = out["errors"][:50]
    return out
