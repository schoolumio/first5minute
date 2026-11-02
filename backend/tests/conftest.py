"""Test configuration: a real PostgreSQL test database migrated with Alembic.

Set TEST_DATABASE_URL to override (default: local projectfive_test).
"""

from __future__ import annotations

import os

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://five:five@localhost:5432/projectfive_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ENVIRONMENT"] = "test"
os.environ["EMAIL_BACKEND"] = "memory"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["FOOTBALL_PROVIDER"] = "demo"
os.environ["FOOTBALL_ALLOW_ALL_LEAGUES"] = "true"   # tests use mock providers without an allowlist
os.environ["PAYMENT_PROVIDER"] = "none"
os.environ["ODDS_PROVIDER"] = "none"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["REDIS_URL"] = "redis://localhost:6390/0"  # unused port -> in-memory rate limiter fallback

from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import Base, SessionLocal, get_engine, utcnow  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Plan, Role, Subscription, User  # noqa: E402
from app.services import email as email_service  # noqa: E402

REFERENCE_TABLES = ["roles", "plans", "betting_markets", "settlement_rules", "platform_settings"]
PASSWORD = "Sup3rSecretPass"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    get_settings.cache_clear()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    cfg.attributes["database_url"] = os.environ["DATABASE_URL"]
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = get_engine()
    snapshot = {}
    with engine.connect() as conn:
        for t in REFERENCE_TABLES:
            snapshot[t] = [dict(r) for r in conn.execute(select(Base.metadata.tables[t])).mappings()]
    yield snapshot


@pytest.fixture(autouse=True)
def clean_db(migrated_db):
    yield
    engine = get_engine()
    tables = [t.name for t in reversed(Base.metadata.sorted_tables)]
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        for t in REFERENCE_TABLES:
            rows = migrated_db[t]
            if rows:
                conn.execute(Base.metadata.tables[t].insert(), rows)
            if "id" in Base.metadata.tables[t].c:
                conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT MAX(id) FROM {t}))"))
    email_service.OUTBOX.clear()
    from app.core.ratelimit import limiter

    limiter.reset()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_user(db, email="user@example.com", role="user", plan: str | None = None, verified=True) -> User:
    r = db.scalar(select(Role).where(Role.name == role))
    u = User(email=email, password_hash=hash_password(PASSWORD), role_id=r.id, full_name="Test User",
             email_verified_at=utcnow() if verified else None, notification_prefs={"scanner_qualified": True})
    db.add(u)
    db.flush()
    if plan and plan != "free":
        p = db.scalar(select(Plan).where(Plan.code == plan))
        db.add(Subscription(user_id=u.id, plan_id=p.id, status="active", current_period_start=utcnow(),
                            current_period_end=utcnow() + timedelta(days=30), payment_provider="test"))
    db.commit()
    return u


def login(client: TestClient, email: str, password: str = PASSWORD) -> TestClient:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = client.cookies.get("pf_csrf")
    return client


@pytest.fixture
def user_factory(db):
    def factory(**kw):
        return make_user(db, **kw)

    return factory
