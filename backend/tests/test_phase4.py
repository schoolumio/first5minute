"""Phase 4: eligibility rules, notifications, performance trend, backfill, config lookup."""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.database import utcnow
from app.engine.settlement import Rule
from app.ingestion.service import Ingestor
from app.ingestion.sync import backfill_history
from app.models import Competition, Fixture, Notification, Prediction, SavedMatch, User
from app.providers.football.base import FootballDataProvider
from app.scanner.eligibility import BLOCK_PREFIX, assess_competitions, classify
from app.scanner.service import run_scan, settle_predictions
from app.services.email import OUTBOX
from tests import factories as f
from tests.conftest import login

CFG = {"lookback_days": 365, "min_finished": 20, "min_coverage": 0.7,
       "high": {"min_finished": 100, "min_coverage": 0.95}, "medium": {"min_finished": 40, "min_coverage": 0.8}}


def test_classify_tiers():
    assert classify(5, 5, CFG)[:2] == ("unassessed", "unknown")
    assert classify(30, 10, CFG)[:2] == ("ineligible", "low")
    assert classify(30, 29, CFG)[:2] == ("eligible", "low")        # fine coverage, small sample
    assert classify(60, 52, CFG)[:2] == ("eligible", "medium")
    assert classify(150, 148, CFG)[:2] == ("eligible", "high")
    status, tier, cov, reason = classify(100, 69, CFG)
    assert status == "ineligible" and "69%" in reason and cov == pytest.approx(0.69)


@pytest.fixture
def league(db):
    """Complete-timeline history for six teams + two upcoming fixtures (low early-goal rate so predictions qualify)."""
    now = utcnow()
    ing = Ingestor(db, "mock", False, Rule())
    for nf in f.season_history(now - timedelta(days=60), n_teams=6, rounds=14, early_goal_every=50):
        ing.ingest_fixture(nf)
    ing.ingest_fixture(f.upcoming("u1", 1, 2, now + timedelta(hours=20)))
    ing.ingest_fixture(f.upcoming("u2", 3, 4, now + timedelta(hours=22)))
    db.commit()
    return now, ing


def _add_untimed(db, ing, n, now):
    for i in range(n):  # finished matches whose event timeline was never provided
        ing.ingest_fixture(f.fixture(f"notl{i}", 1 + i % 5, 2 + i % 5, now - timedelta(days=100, hours=i), None, score=(1, 0)))
    db.commit()


def test_assess_sets_tier_coverage_and_reason(db, league):
    now, ing = league
    comp = db.scalar(select(Competition))
    assess_competitions(db, now)
    assert comp.eligibility_status == "eligible" and comp.data_quality_tier == "medium" and comp.coverage_pct == 1.0
    _add_untimed(db, ing, 40, now)
    assess_competitions(db, now)
    assert comp.eligibility_status == "ineligible" and comp.coverage_pct < 0.7
    assert comp.finished_count > 70 and "reconciled event timeline" in comp.eligibility_reason


def test_ineligible_competition_is_excluded_with_reason_and_override_works(db, league):
    now, ing = league
    _add_untimed(db, ing, 40, now)
    run_scan(db, now=now, notify=False)
    db.commit()
    preds = db.scalars(select(Prediction).where(Prediction.is_current)).all()
    assert len(preds) == 4 and all(p.category == "excluded" for p in preds)
    assert all(p.category_reasons[0].startswith(BLOCK_PREFIX) for p in preds)
    # Idempotent while nothing changes
    assert run_scan(db, now=now + timedelta(minutes=1), notify=False).predictions_created == 0
    # Admin forces the competition on -> new (qualifying-capable) predictions supersede the exclusions.
    comp = db.scalar(select(Competition))
    comp.eligibility_mode = "force_on"
    db.commit()
    run_scan(db, now=now + timedelta(minutes=2), notify=False)
    db.commit()
    cur = db.scalars(select(Prediction).where(Prediction.is_current)).all()
    assert len(cur) == 4 and all(p.category != "excluded" for p in cur)
    assert db.scalar(select(Prediction.id).where(~Prediction.is_current).limit(1)) is not None   # history kept
    # And force_off excludes even a healthy competition.
    comp.eligibility_mode = "force_off"
    db.commit()
    run_scan(db, now=now + timedelta(minutes=3), notify=False)
    db.commit()
    assert all(p.category == "excluded" and "administrator" in p.category_reasons[0]
               for p in db.scalars(select(Prediction).where(Prediction.is_current)))


def test_admin_can_assess_and_override_via_api(client, db, user_factory, league):
    user_factory(email="elig-admin@example.com", role="admin")
    login(client, "elig-admin@example.com")
    r = client.post("/api/v1/admin/competitions/assess")
    assert r.status_code == 200 and r.json()["assessed"] == 1
    comps = client.get("/api/v1/admin/competitions").json()
    assert comps[0]["eligibility_status"] == "eligible" and comps[0]["data_quality_tier"] == "medium"
    cid = comps[0]["id"]
    assert client.patch(f"/api/v1/admin/competitions/{cid}", json={"eligibility_mode": "bogus"}).status_code == 422
    assert client.patch(f"/api/v1/admin/competitions/{cid}", json={"eligibility_mode": "force_off"}).json()["eligibility_mode"] == "force_off"


# ------------------------------------------------------------------ notifications
def _pro(user_factory, address, **prefs):
    u = user_factory(email=address, plan="pro")
    u.notification_prefs = {"scanner_qualified": True, "prediction_settled": False, "email": False, **prefs}
    return u


def test_qualified_notifications_in_app_and_email_digest(db, user_factory, league):
    now, _ = league
    _pro(user_factory, "mail@example.com", email=True)
    _pro(user_factory, "inapp@example.com")
    _pro(user_factory, "optout@example.com", scanner_qualified=False, email=True)
    user_factory(email="free@example.com")
    db.commit()
    s = run_scan(db, now=now)
    db.commit()
    assert s.newly_qualified
    users = {u.email: u.id for u in db.scalars(select(User))}
    counts = {e: len(db.scalars(select(Notification).where(Notification.user_id == uid)).all()) for e, uid in users.items()}
    assert counts["mail@example.com"] == len(s.newly_qualified) and counts["inapp@example.com"] == len(s.newly_qualified)
    assert counts["optout@example.com"] == 0 and counts["free@example.com"] == 0
    assert [m.to for m in OUTBOX] == ["mail@example.com"]                      # only the opted-in user gets a digest
    assert "newly qualified" in OUTBOX[0].subject and "not guarantees" in OUTBOX[0].body


def test_settlement_notifies_only_eligible_users_who_saved_the_match(db, user_factory, league):
    now, ing = league
    a = _pro(user_factory, "saver@example.com", prediction_settled=True)
    b = _pro(user_factory, "nosave@example.com", prediction_settled=True)
    c = _pro(user_factory, "pref-off@example.com", prediction_settled=False)
    d = user_factory(email="free-saver@example.com")
    d.notification_prefs = {"prediction_settled": True}
    db.commit()
    run_scan(db, now=now, notify=False)
    db.commit()
    fx = db.scalar(select(Fixture).where(Fixture.provider_id == "u1"))
    for u in (a, c, d):
        db.add(SavedMatch(user_id=u.id, fixture_id=fx.id))
    db.commit()
    ing.ingest_fixture(f.fixture("u1", 1, 2, fx.kickoff_at, [f.goal(30, "mt1")]))
    db.commit()
    settle_predictions(db)
    db.commit()
    notes = db.scalars(select(Notification).where(Notification.kind == "prediction_settled")).all()
    assert [n.user_id for n in notes] == [a.id] and b.id not in [n.user_id for n in notes]
    assert "Score at 5': 0-0" in notes[0].body and "correct" in notes[0].body
    # A provider correction re-settles but does not spam a second notification.
    ing.ingest_fixture(f.fixture("u1", 1, 2, fx.kickoff_at, [f.goal(4, "mt1")]))
    db.commit()
    settle_predictions(db)
    db.commit()
    assert db.scalar(select(Notification).where(Notification.kind == "prediction_settled").limit(1).offset(1)) is None


# ------------------------------------------------------------------ trend
def test_performance_trend_buckets_and_plan_cap(client, db, user_factory, league):
    now, ing = league
    run_scan(db, now=now, notify=False)
    db.commit()
    for pid, home, away in (("u1", 1, 2), ("u2", 3, 4)):
        fx = db.scalar(select(Fixture).where(Fixture.provider_id == pid))
        goals = [f.goal(30, f"mt{home}")] if pid == "u1" else [f.goal(3, f"mt{home}")]
        ing.ingest_fixture(f.fixture(pid, home, away, fx.kickoff_at, goals))
    db.commit()
    settle_predictions(db)
    db.commit()
    user_factory(email="trend-free@example.com")
    user_factory(email="trend-pro@example.com", plan="pro")
    login(client, "trend-free@example.com")
    free = client.get("/api/v1/predictions/performance/trend", params={"market": "MARKET_A", "days": 365}).json()
    assert free["capped_by_plan"] is True and free["days"] == 30
    pts = free["points"]
    assert sum(p["n"] for p in pts) == 2 and pts[0]["hit_rate"] == 0.5 and 0 < pts[0]["mean_predicted"] < 1
    assert pts[0]["brier"] is not None and "n" in free["note"]
    client.cookies.clear()
    login(client, "trend-pro@example.com")
    pro = client.get("/api/v1/predictions/performance/trend", params={"market": "MARKET_A", "days": 365, "bucket": "day"}).json()
    assert pro["capped_by_plan"] is False and pro["days"] == 365 and pro["bucket"] == "day"
    assert client.get("/api/v1/predictions/performance/trend", params={"market": "X"}).status_code == 422


# ------------------------------------------------------------------ backfill
class FakeProvider(FootballDataProvider):
    name, is_demo = "mock", False

    def __init__(self):
        self.calls: list[date] = []

    def fixtures_by_date(self, day):
        self.calls.append(day)
        ko = datetime(day.year, day.month, day.day, 15, tzinfo=UTC)
        return [f.fixture(f"bf-{day.isoformat()}", 1, 2, ko, [f.goal(30, "mt1")])]

    def fixture_with_events(self, provider_fixture_id):
        day = date.fromisoformat(provider_fixture_id[3:])
        return self.fixtures_by_date(day)[0]

    def team_recent_fixtures(self, provider_team_id, last=20):
        return []


def test_backfill_is_resumable_and_force_refetches(db):
    p = FakeProvider()
    seen = []
    out = backfill_history(db, p, days=10, chunk_days=4, progress=lambda d, t: seen.append(d))
    assert out["days_synced"] == 10 and out["fixtures_created"] == 10 and len(seen) == 3
    assert min(p.calls) < max(p.calls)                                           # oldest first
    assert db.scalar(select(Fixture.id).where(Fixture.provider_id == "bf-" + p.calls[0].isoformat())) is not None
    p2 = FakeProvider()
    again = backfill_history(db, p2, days=12, chunk_days=5)
    assert again["days_skipped"] == 10 and again["days_synced"] == 2 and len(p2.calls) >= 2
    p3 = FakeProvider()
    forced = backfill_history(db, p3, days=5, force=True)
    assert forced["days_synced"] == 5 and forced["fixtures_created"] == 0 and forced["fixtures_updated"] == 5


# ------------------------------------------------------------------ config
def test_env_file_lookup_prefers_backend_over_repo_root(tmp_path, monkeypatch):
    from app.core.config import Settings

    (tmp_path / ".env").write_text("APP_NAME=FromRoot\nFRONTEND_URL=http://root.example\n")
    backend = tmp_path / "backend"
    backend.mkdir()
    (backend / ".env").write_text("FRONTEND_URL=http://backend.example\n")
    monkeypatch.chdir(backend)
    for var in ("APP_NAME", "FRONTEND_URL"):
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.app_name == "FromRoot" and s.frontend_url == "http://backend.example"


@pytest.mark.parametrize("raw,expected", [
    ("http://localhost:3000", ["http://localhost:3000"]),
    ("http://a.example, http://b.example", ["http://a.example", "http://b.example"]),
    ('["http://c.example"]', ["http://c.example"]),
])
def test_cors_origins_accept_plain_comma_and_json_forms(monkeypatch, raw, expected):
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings().cors_origins == expected


def test_shipped_env_example_is_loadable(monkeypatch, tmp_path):
    """Regression: copying .env.example verbatim must produce a working configuration."""
    from pathlib import Path

    from app.core.config import Settings

    example = Path(__file__).resolve().parents[2] / ".env.example"
    for line in example.read_text().splitlines():          # tests pin their own values; clear them so the file is what is read
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.startswith("#"):
            monkeypatch.delenv(key.upper(), raising=False)
    s = Settings(_env_file=example)
    assert s.football_provider == "demo" and s.cors_origins == ["http://localhost:3000"] and s.environment == "development"
