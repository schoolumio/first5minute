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
    ProviderPlanLimit,
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


# ================================================================== season download, plan limits, diagnostics
from app.ingestion.sync import sync_league_season  # noqa: E402


class SeasonFake(FakeFootball):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.season_calls: list[tuple[str, int]] = []
        self.plan_limit_on_season = False
        self.plan_limit_on_events = False

    def add_upcoming(self, day: date, idx: int):
        ko = datetime(day.year, day.month, day.day, 15, tzinfo=UTC)
        fid = f"up-{day.isoformat()}-{idx}"
        self.detail[fid] = f.upcoming(fid, 1 + idx % 5, 2 + idx % 4 + (1 if idx % 4 == 0 else 0), ko)
        return fid

    def fixtures_by_league_season(self, league_id, season):
        self.season_calls.append((league_id, season))
        if self.plan_limit_on_season:
            raise ProviderPlanLimit("Free plans do not have access to this season")
        return [dataclasses.replace(v, events=None) for v in self.detail.values() if v.competition.provider_id == league_id]

    def fixtures_with_events(self, ids):
        if self.plan_limit_on_events:
            raise ProviderPlanLimit("plan does not include events")
        return super().fixtures_with_events(ids)


def _season(p: SeasonFake, n_finished=7, n_upcoming=2):
    for i in range(n_finished):
        p.add(TODAY - timedelta(days=60 - i), i)
    for i in range(n_upcoming):
        p.add_upcoming(TODAY + timedelta(days=1 + i), i)


def test_season_download_is_one_listing_request_plus_bulk_timelines(db):
    p = SeasonFake()
    _season(p)
    out = sync_league_season(db, p, "mock-l1", 2026)
    assert p.season_calls == [("mock-l1", 2026)]
    assert [len(c) for c in p.batch_calls] == [3, 3, 1]                                     # 3 bulk requests for 7 timelines
    assert out["fixtures"] == 9 and out["finished"] == 7 and out["timelines_fetched"] == 7 and out["timelines_missing"] == 0
    assert out["stopped_reason"] is None and not out["errors"]
    rows = db.scalars(select(Fixture)).all()
    assert len(rows) == 9 and sum(1 for r in rows if r.status == "scheduled") == 2           # upcoming fixtures are stored too
    assert db.scalar(select(SyncRun.status).where(SyncRun.job == "sync_season")) == "success"


def test_season_download_resumes_after_quota_and_skips_finished_work(db):
    p = SeasonFake(quota_after_batches=1)
    _season(p)
    first = sync_league_season(db, p, "mock-l1", 2026)
    assert "run the same command again" in first["stopped_reason"] and 0 < first["timelines_fetched"] < 7
    assert first["timelines_missing"] == 7 - first["timelines_fetched"]
    p.quota_after_batches = None
    p.batch_calls.clear()
    second = sync_league_season(db, p, "mock-l1", 2026)
    assert second["stopped_reason"] is None and second["timelines_missing"] == 0
    assert sum(len(c) for c in p.batch_calls) == 7 - first["timelines_fetched"]              # only the missing ones were fetched
    p.batch_calls.clear()
    third = sync_league_season(db, p, "mock-l1", 2026)
    assert p.batch_calls == [] and third["timelines_fetched"] == 0                           # nothing left to do: no wasted requests


def test_season_download_reports_plan_limits_clearly(db):
    p = SeasonFake()
    _season(p)
    p.plan_limit_on_season = True
    out = sync_league_season(db, p, "mock-l1", 2026)
    assert "Free plans" in out["stopped_reason"] and out["fixtures"] == 0
    assert db.scalar(select(SyncRun.status).where(SyncRun.job == "sync_season")) == "failed"
    p.plan_limit_on_season, p.plan_limit_on_events = False, True
    out2 = sync_league_season(db, p, "mock-l1", 2026)
    assert out2["stopped_reason"] == "plan does not include events" and out2["fixtures"] == 9      # schedule saved, timelines not


def test_api_football_plan_errors_and_season_request():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        if request.url.params.get("season") == "2026":
            return httpx.Response(200, json={"errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."},
                                             "response": []})
        return httpx.Response(200, json={"errors": [], "response": [_item(1), _item(2)]})

    prov = api_football.ApiFootballProvider(client=_client(handler))
    ok = prov.fixtures_by_league_season("39", 2023)
    assert len(ok) == 2 and seen[-1]["league"] == "39" and seen[-1]["season"] == "2023"
    with pytest.raises(ProviderPlanLimit) as e:
        prov.fixtures_by_league_season("39", 2026)
    assert "check your plan" in str(e.value) and "backfill-season" in str(e.value) and not isinstance(e.value, ProviderQuotaExceeded)
    date_err = {"errors": {"plan": "Free plans do not have access to this date, try from 2026-11-01 to 2026-11-03."}, "response": []}
    prov2 = api_football.ApiFootballProvider(client=_client(lambda r: httpx.Response(200, json=date_err)))
    with pytest.raises(ProviderPlanLimit) as e2:
        prov2.fixtures_by_date(date(2026, 1, 1))
    assert e2.value.window == (date(2026, 11, 1), date(2026, 11, 3))


def test_day_sync_and_backfill_stop_on_plan_limit_without_wasting_requests(db):
    class Limited(SeasonFake):
        def fixtures_by_date(self, day):
            self.day_calls.append(day)
            raise ProviderPlanLimit("Free plans do not have access to this date")

    p = Limited()
    out = backfill_history(db, p, days=10, chunk_days=2)
    assert "Free plans" in out["stopped_reason"] and len(p.day_calls) == 1                  # stopped after the FIRST refused request
    stats = sync_days(db, Limited(), [TODAY], league_ids=None)
    assert stats.plan_limited and not stats.quota_exhausted


def test_diagnostics_report_errors_instead_of_crashing_and_probe_a_season():
    class AllRefused(SeasonFake):
        def fixtures_by_date(self, day):
            raise ProviderPlanLimit("Free plans do not have access to this date")

    r = check_provider(AllRefused(), TODAY, {"mock-l1"})
    assert all("error" in d for d in r["days"]) and "older season" in r["verdict"] and "--season" in r["verdict"]
    one = SeasonFake()
    day = TODAY - timedelta(days=30)
    one.add(day, 0, minute=3)
    r2 = check_provider(one, TODAY, {"mock-l1"}, only_day=day)
    assert len(r2["days"]) == 1 and r2["sample_fixture"]["score_at_5_minutes"] == "1-0" and r2["verdict"].startswith("OK")
    from app.ingestion.diagnostics import check_season

    s = SeasonFake()
    _season(s, n_finished=7, n_upcoming=1)
    rep = check_season(s, "mock-l1", 2023)
    assert rep["fixtures_in_season"] == 8 and rep["finished"] == 7 and rep["requests_to_download_if_plan_allows_bulk"] == 1 + 1 and rep["requests_to_download_if_one_per_match"] == 1 + 7
    assert rep["verdict"].startswith("OK")
    s.plan_limit_on_season = True
    assert "Request refused" in check_season(s, "mock-l1", 2026)["verdict"]


def test_backtest_job_accepts_a_historical_window(db):
    from datetime import timedelta as td

    from app.engine.settlement import Rule
    from app.ingestion.service import Ingestor
    from app.workers.jobs import job_backtest

    old = datetime.now(UTC) - td(days=400)
    ing = Ingestor(db, "mock", False, Rule())
    for nf in f.season_history(old, n_teams=6, rounds=14):
        ing.ingest_fixture(nf)
    db.commit()
    recent_only = job_backtest(db, days=60)
    assert recent_only["MARKET_A"]["sample_size"] == 0                                       # nothing in the last 60 days
    hist = job_backtest(db, start=old - td(days=1), end=old + td(days=60))
    assert hist["MARKET_A"]["sample_size"] > 0 and hist["is_demo"] is False and len(hist["window"]) == 2


# ================================================================== free plan: bulk `ids` refused -> one timeline per request
def _dated(fid: int, day_offset: int) -> dict:
    from tests.test_providers import APIF_FIXTURE

    item = _item(fid)
    d = datetime(2023, 8, 12, 14, tzinfo=UTC) + timedelta(days=day_offset)
    item["fixture"] = {**APIF_FIXTURE["fixture"], "id": fid, "date": d.isoformat()}
    return item


class FreePlanApi:
    """Mock API-Football on a free plan: list OK, bulk ids refused, single-fixture lookups until the daily limit."""

    def __init__(self, n=8, singles_before_limit: int | None = None):
        self.n, self.limit = n, singles_before_limit
        self.single_ids: list[int] = []
        self.bulk_refusals = 0
        self.lists = 0

    def handler(self, request):
        p = request.url.params
        if request.url.path.endswith("/status"):
            return httpx.Response(200, json={"errors": [], "response": {"requests": {"current": 7, "limit_day": 100}}})
        if "ids" in p:
            self.bulk_refusals += 1
            return httpx.Response(200, json={"errors": {"plan": "Free plans do not have access to the Ids parameter."}, "response": []})
        if "id" in p:
            if self.limit is not None and len(self.single_ids) >= self.limit:
                return httpx.Response(200, json={"errors": {"requests": "You have reached the request limit for the day"}, "response": []})
            self.single_ids.append(int(p["id"]))
            return httpx.Response(200, json={"errors": [], "response": [_dated(int(p["id"]), int(p["id"]))]})
        self.lists += 1
        return httpx.Response(200, json={"errors": [], "response": [_dated(i, i) for i in range(self.n, 0, -1)]})   # newest first!

    def provider(self):
        return api_football.ApiFootballProvider(client=_client(self.handler))


def test_free_plan_fallback_is_automatic_chronological_and_resumes_across_days(db):
    api = FreePlanApi(n=8, singles_before_limit=5)
    first = sync_league_season(db, api.provider(), "39", 2023)
    assert api.bulk_refusals == 1 and api.lists == 1                                   # tried bulk once, then never again
    assert api.single_ids == [1, 2, 3, 4, 5]                                           # oldest matches first despite newest-first listing
    assert first["timelines_fetched"] == 5 and first["timelines_missing"] == 3
    assert "run the same command again" in first["stopped_reason"]
    assert "3 timelines still to download" in first["stopped_reason"] and "1 more daily run" in first["stopped_reason"]
    assert db.scalar(select(SyncRun.status).where(SyncRun.job == "sync_season")) == "quota_hit"

    # "tomorrow": a fresh process/provider, quota available again - only the missing three are requested
    api.limit, api.single_ids = None, []
    second = sync_league_season(db, api.provider(), "39", 2023)
    assert api.single_ids == [6, 7, 8] and second["timelines_fetched"] == 3 and second["timelines_missing"] == 0
    assert second["stopped_reason"] is None
    api.single_ids.clear()
    third = sync_league_season(db, api.provider(), "39", 2023)
    assert api.single_ids == [] and third["timelines_fetched"] == 0                    # nothing left: no wasted requests
    assert all(x.timeline_status == "complete" for x in db.scalars(select(Fixture)))


def test_provider_fallback_state_and_partial_results_on_quota():
    api = FreePlanApi(n=5, singles_before_limit=2)
    prov = api.provider()
    assert prov.events_batch_size == 20
    with pytest.raises(ProviderQuotaExceeded) as e:
        prov.fixtures_with_events([str(i) for i in range(1, 6)])
    assert [x.provider_id for x in e.value.partial] == ["1", "2"]                       # work done before the limit is returned, not lost
    assert prov.events_batch_size == 1 and prov._bulk_ok is False
    api.limit = None
    assert [x.provider_id for x in prov.fixtures_with_events(["3", "4"])] == ["3", "4"]
    assert api.bulk_refusals == 1                                                       # never retried after the first refusal


def test_other_plan_errors_are_not_mistaken_for_the_bulk_restriction():
    other = {"errors": {"plan": "Free plans do not have access to this season, try from 2021 to 2023."}, "response": []}
    prov = api_football.ApiFootballProvider(client=_client(lambda r: httpx.Response(200, json=other)))
    with pytest.raises(ProviderPlanLimit):
        prov.fixtures_with_events(["1", "2"])
    assert prov._bulk_ok is True                                                        # no silent fallback for unrelated plan limits


class WindowedFake(FakeFootball):
    """A plan that serves only yesterday..tomorrow and refuses any other date (like API-Football's free plan)."""

    def fixtures_by_date(self, day):
        if not (TODAY - timedelta(days=1) <= day <= TODAY + timedelta(days=1)):
            self.day_calls.append(day)
            raise ProviderPlanLimit(f"Free plans do not have access to this date, try from {TODAY - timedelta(days=1)} to "
                                    f"{TODAY + timedelta(days=1)}.", window=(TODAY - timedelta(days=1), TODAY + timedelta(days=1)))
        return super().fixtures_by_date(day)             # records the call itself


def test_date_window_plan_syncs_the_allowed_days_and_wastes_one_request(db):
    p = WindowedFake()
    p.add(TODAY + timedelta(days=1), 1)
    p.add(TODAY, 2)
    p.add(TODAY - timedelta(days=1), 3)
    days = [TODAY + timedelta(days=d) for d in (-3, -2, -1, 0, 1, 2, 3)]       # oldest first, as a naive caller would
    stats = sync_days(db, p, days, league_ids=None)
    assert stats.fixtures_created == 3 and not stats.plan_limited and not stats.quota_exhausted
    assert stats.days_outside_plan == 4 and len(p.day_calls) == 4                # 3 allowed days + ONE refused probe
    assert db.scalar(select(SyncRun.status).order_by(SyncRun.id.desc())) == "success"


def test_sync_window_asks_for_the_days_nearest_today_first(db):
    from app.ingestion.sync import sync_window

    p = WindowedFake()
    p.add(TODAY + timedelta(days=1), 1)
    stats = sync_window(db, p, past_days=2, future_days=3)
    assert p.day_calls[:3] == [TODAY, TODAY + timedelta(days=1), TODAY - timedelta(days=1)]
    assert stats.fixtures_created == 1 and stats.days_outside_plan == 3 and len(p.day_calls) == 4
