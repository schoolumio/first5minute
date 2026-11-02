"""Real-data readiness: league allowlist, bulk event fetch, quota-aware resumable backfill, diagnostics."""

import dataclasses
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.ingestion.diagnostics import check_provider
from app.ingestion.sync import backfill_history, league_scope, sync_days
from app.models import Fixture, SyncRun
from app.providers.football import api_football
from app.providers.football.base import (
    FootballDataProvider,
    LeagueScopeError,
    NormalizedCompetition,
    ProviderQuotaExceeded,
)
from app.providers.http import ProviderHttpClient
from tests import factories as f
from tests.conftest import login

OTHER = NormalizedCompetition(provider_id="other-l2", name="Other League", country="Elsewhere", season_label="2026")
TODAY = datetime.now(UTC).date()


class FakeFootball(FootballDataProvider):
    name, is_demo, events_batch_size = "mock", False, 3

    def __init__(self, quota_after_batches: int | None = None):
        self.detail: dict[str, object] = {}
        self.by_day: dict[date, list[str]] = {}
        self.batch_calls: list[list[str]] = []
        self.quota_after_batches = quota_after_batches
        self.day_calls: list[date] = []
        self.quota_on_days: set[date] = set()

    def add(self, day: date, idx: int, comp=f.COMP, minute: int = 30, events: bool = True, score=None):
        ko = datetime(day.year, day.month, day.day, 12 + idx % 6, tzinfo=UTC)
        fid = f"fx-{day.isoformat()}-{idx}-{comp.provider_id}"
        nf = f.fixture(fid, 1 + idx % 5, 2 + idx % 4 + (1 if idx % 4 == 0 else 0), ko, [f.goal(minute, f"mt{1 + idx % 5}")] if events else [],
                       comp=comp, score=score)
        self.detail[fid] = nf
        self.by_day.setdefault(day, []).append(fid)
        return fid

    def fixtures_by_date(self, day):
        self.day_calls.append(day)
        if day in self.quota_on_days:
            raise ProviderQuotaExceeded("daily limit")
        return [dataclasses.replace(self.detail[i], events=None) for i in self.by_day.get(day, [])]

    def fixture_with_events(self, provider_fixture_id):
        return self.detail[provider_fixture_id]

    def fixtures_with_events(self, ids):
        self.batch_calls.append(list(ids))
        if self.quota_after_batches is not None and len(self.batch_calls) > self.quota_after_batches:
            raise ProviderQuotaExceeded("daily limit")
        return [self.detail[i] for i in ids]

    def team_recent_fixtures(self, provider_team_id, last=20):
        return []


@pytest.fixture
def strict_scope(monkeypatch):
    """Behave like a real deployment: allowlist required."""
    s = get_settings()
    monkeypatch.setattr(s, "football_allow_all_leagues", False)
    monkeypatch.setattr(s, "football_league_ids", [])
    return s


def test_league_scope_rules(strict_scope, monkeypatch):
    real = FakeFootball()
    with pytest.raises(LeagueScopeError, match="FOOTBALL_LEAGUE_IDS"):
        league_scope(real)
    monkeypatch.setattr(strict_scope, "football_league_ids", [" 39 ", "140", ""])
    assert league_scope(real) == {"39", "140"}
    monkeypatch.setattr(strict_scope, "football_league_ids", [])
    monkeypatch.setattr(strict_scope, "football_allow_all_leagues", True)
    assert league_scope(real) is None
    demo = FakeFootball()
    demo.is_demo = True
    monkeypatch.setattr(strict_scope, "football_allow_all_leagues", False)
    assert league_scope(demo) is None


def test_sync_refuses_to_run_without_allowlist_and_skips_politely_in_jobs(db, strict_scope, monkeypatch):
    p = FakeFootball()
    with pytest.raises(LeagueScopeError):
        sync_days(db, p, [TODAY])
    assert p.day_calls == [] and db.scalar(select(SyncRun.id)) is None                    # no request spent, no run recorded
    from app.workers import jobs

    monkeypatch.setattr(jobs, "get_provider", lambda _db: p)
    assert "FOOTBALL_LEAGUE_IDS" in jobs.job_sync(db)["skipped"]


def test_only_allowlisted_leagues_are_ingested_and_counted(db):
    p = FakeFootball()
    day = TODAY - timedelta(days=2)
    for i in range(3):
        p.add(day, i)
    for i in range(4):
        p.add(day, 10 + i, comp=OTHER)
    stats = sync_days(db, p, [day], league_ids={"mock-l1"})
    assert stats.fixtures_created == 3 and stats.filtered_out == 4
    assert {x.competition.provider_id for x in db.scalars(select(Fixture))} == {"mock-l1"}
    assert sum(len(c) for c in p.batch_calls) == 3                                         # no timelines wasted on other leagues


def test_event_timelines_are_fetched_in_bulk(db):
    p = FakeFootball()
    day = TODAY - timedelta(days=2)
    for i in range(7):
        p.add(day, i)
    stats = sync_days(db, p, [day], league_ids={"mock-l1"})
    assert [len(c) for c in p.batch_calls] == [3, 3, 1]                                    # 3 requests instead of 7
    assert stats.fixtures_created == 7 and stats.events_replaced == 7 and not stats.errors
    assert all(x.timeline_status == "complete" for x in db.scalars(select(Fixture)))


def test_quota_stop_keeps_progress_and_backfill_resumes(db):
    p = FakeFootball(quota_after_batches=2)        # day 1 (2 bulk requests) completes; the quota dies during day 2
    days = [TODAY - timedelta(days=d) for d in (3, 2, 1)]
    for d in days:
        for i in range(4):
            p.add(d, i)
    # first run: quota dies on the third bulk request (first request of day 2)
    out = backfill_history(db, p, days=3, chunk_days=1)
    assert out["stopped_reason"] and "run the same command again" in out["stopped_reason"]
    assert db.scalar(select(SyncRun.status).where(SyncRun.job == "sync_fixtures").order_by(SyncRun.id.desc())) == "quota_hit"
    first = db.scalars(select(Fixture)).all()
    assert first and any(x.events_synced_at is None for x in first)                        # saved, but some timelines still missing
    # quota resets: same command resumes - the interrupted day is retried, finished days are skipped
    p.quota_after_batches = None
    p.batch_calls.clear()
    out2 = backfill_history(db, p, days=3, chunk_days=1)
    assert out2["stopped_reason"] is None and out2["days_skipped"] == 1 and out2["days_synced"] == 2
    db.expire_all()
    assert all(x.events_synced_at is not None and x.timeline_status == "complete" for x in db.scalars(select(Fixture)))
    assert db.scalar(select(Fixture.id).where(Fixture.provider_id.like("fx-%")).limit(1)) is not None
    assert len(db.scalars(select(Fixture)).all()) == 12


def test_quota_on_fixture_listing_stops_cleanly(db):
    p = FakeFootball()
    d1, d2 = TODAY - timedelta(days=3), TODAY - timedelta(days=2)
    for i in range(2):
        p.add(d1, i)
        p.add(d2, i)
    p.quota_on_days.add(d2)
    stats = sync_days(db, p, [d1, d2], league_ids={"mock-l1"})
    assert stats.quota_exhausted and stats.fixtures_created == 2
    assert p.day_calls == [d1, d2]


# ------------------------------------------------------------------ API-Football adapter
def _client(handler):
    return ProviderHttpClient("mock", "https://mock.test", transport=httpx.MockTransport(handler), per_minute=6000,
                              sleep=lambda s: None, log_calls=False)


def _item(fid):
    from tests.test_providers import APIF_FIXTURE

    return {**APIF_FIXTURE, "fixture": {**APIF_FIXTURE["fixture"], "id": fid}}


def test_api_football_bulk_events_batches_of_twenty():
    seen = []

    def handler(request):
        ids = request.url.params["ids"].split("-")
        seen.append(ids)
        return httpx.Response(200, json={"errors": [], "response": [_item(int(i)) for i in ids]})

    prov = api_football.ApiFootballProvider(client=_client(handler))
    out = prov.fixtures_with_events([str(i) for i in range(1, 46)])
    assert [len(s) for s in seen] == [20, 20, 5] and len(out) == 45 and all(o.events for o in out)


def test_api_football_quota_error_is_distinguished():
    msg = {"errors": {"requests": "You have reached the request limit for the day, Go to ... to upgrade your Plan."}, "response": []}
    prov = api_football.ApiFootballProvider(client=_client(lambda r: httpx.Response(200, json=msg)))
    with pytest.raises(ProviderQuotaExceeded):
        prov.fixtures_by_date(date(2026, 10, 3))
    other = api_football.ApiFootballProvider(client=_client(lambda r: httpx.Response(200, json={"errors": {"token": "bad"}, "response": []})))
    with pytest.raises(api_football.b.ProviderError) as e:
        other.fixtures_by_date(date(2026, 10, 3))
    assert not isinstance(e.value, ProviderQuotaExceeded)


def test_api_football_league_search():
    payload = {"errors": [], "response": [
        {"league": {"id": 39, "name": "Premier League", "type": "League"}, "country": {"name": "England"}},
        {"league": {"id": 40, "name": "Championship", "type": "League"}, "country": {"name": "England"}}]}
    prov = api_football.ApiFootballProvider(client=_client(lambda r: httpx.Response(200, json=payload)))
    assert prov.search_leagues("prem")[0] == {"id": 39, "name": "Premier League", "type": "League", "country": "England"}
    with pytest.raises(NotImplementedError):
        FakeFootball().search_leagues("x")


# ------------------------------------------------------------------ diagnostics
def test_provider_check_reports_reconciliation_and_five_minute_score():
    p = FakeFootball()
    day = TODAY - timedelta(days=1)
    p.add(day, 0, minute=3)
    p.add(day, 1, comp=OTHER)
    report = check_provider(p, TODAY, {"mock-l1"})
    d = next(x for x in report["days"] if x["date"] == day.isoformat())
    assert d["fixtures_all_leagues"] == 2 and d["fixtures_in_allowlist"] == 1 and d["finished"] == 1
    sf = report["sample_fixture"]
    assert sf["timeline_reconciles_with_score"] is True and sf["score_at_5_minutes"] == "1-0" and report["verdict"].startswith("OK")
    bad = FakeFootball()
    bad.add(day, 0, events=False, score=(2, 1))                                             # goals missing from the timeline
    r2 = check_provider(bad, TODAY, {"mock-l1"})
    assert r2["sample_fixture"]["timeline_reconciles_with_score"] is False and r2["verdict"].startswith("WARNING")
    empty = check_provider(FakeFootball(), TODAY, {"mock-l1"})
    assert "No finished fixtures" in empty["verdict"] and "sample_fixture" not in empty


# ------------------------------------------------------------------ config + admin
@pytest.mark.parametrize("raw,expected", [("39", ["39"]), ("39, 140 ,135", ["39", "140", "135"]), ('["2","3"]', ["2", "3"]), ("", [])])
def test_league_ids_env_forms(monkeypatch, raw, expected):
    from app.core.config import Settings

    monkeypatch.setenv("FOOTBALL_LEAGUE_IDS", raw)
    assert Settings().football_league_ids == expected


def test_admin_providers_exposes_league_scope(client, user_factory):
    user_factory(email="scope-admin@example.com", role="admin")
    login(client, "scope-admin@example.com")
    scope = client.get("/api/v1/admin/providers").json()["league_scope"]
    assert scope["required"] is False and scope["league_ids"] == [] and "allow_all" in scope
