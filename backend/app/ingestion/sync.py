"""Synchronisation jobs: pull fixtures/events from the provider into the DB."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utcnow
from app.core.logging import get_logger
from app.ingestion.service import Ingestor, IngestStats
from app.models import Fixture, SyncRun
from app.providers.football.base import FINAL_STATUSES, FootballDataProvider, ProviderError
from app.services.settings import default_rule_row, rule_from_row

log = get_logger(__name__)


def _ingestor(db: Session, provider: FootballDataProvider) -> Ingestor:
    return Ingestor(db, provider.name, provider.is_demo, rule_from_row(default_rule_row(db)))


def sync_days(db: Session, provider: FootballDataProvider, days: list[date], with_events_for_final: bool = True) -> IngestStats:
    """Ingest fixtures for each day; fetch full timelines for final fixtures.

    Each fixture is committed in its own savepoint so one bad record cannot
    abort the whole run; errors are collected and reported.
    """
    run = SyncRun(job="sync_fixtures", provider=provider.name, status="running")
    db.add(run)
    db.commit()
    ing = _ingestor(db, provider)
    try:
        for day in days:
            for nf in provider.fixtures_by_date(day):
                try:
                    with db.begin_nested():
                        if with_events_for_final and (nf.status in FINAL_STATUSES or nf.status == "abandoned"):
                            nf = provider.fixture_with_events(nf.provider_id)
                        ing.ingest_fixture(nf)
                except (ProviderError, ValueError) as exc:
                    ing.stats.errors.append(f"{nf.provider_id}: {exc}")
            db.commit()
        run.status = "success" if not ing.stats.errors else "partial"
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
    days = [today + timedelta(days=d) for d in range(-past_days, future_days + 1)]
    return sync_days(db, provider, days)
