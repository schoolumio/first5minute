"""User activity and platform operations models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, utcnow
from app.models.football import Fixture


class SavedMatch(TimestampMixin, Base):
    __tablename__ = "saved_matches"
    __table_args__ = (UniqueConstraint("user_id", "fixture_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(String(500))

    fixture: Mapped[Fixture] = relationship(lazy="joined")


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # scanner_match|prediction_settled|billing|system
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(16), default="in_app")


class BetTracking(TimestampMixin, Base):
    """User-recorded bets. Project Five never holds funds or places bets."""

    __tablename__ = "bet_tracking"
    __table_args__ = (Index("ix_bet_tracking_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="RESTRICT"))
    market_code: Mapped[str] = mapped_column(String(32))
    bookmaker_id: Mapped[int | None] = mapped_column(ForeignKey("bookmakers.id", ondelete="SET NULL"))
    decimal_odds: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    stake: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="NGN")
    bet_reference: Mapped[str | None] = mapped_column(String(128))
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    settlement_status: Mapped[str] = mapped_column(String(12), default="pending")  # pending|won|lost|void
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=True)

    fixture: Mapped[Fixture] = relationship(lazy="joined")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataProviderLog(Base):
    """One row per provider request: health, latency and error monitoring."""

    __tablename__ = "data_provider_logs"
    __table_args__ = (Index("ix_provider_logs_provider_created", "provider", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    operation: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12))  # success|error|rate_limited
    http_status: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    records: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderPayload(Base):
    """Raw provider payloads kept for auditing and reprocessing."""

    __tablename__ = "provider_payloads"
    __table_args__ = (
        UniqueConstraint("provider", "entity_type", "provider_entity_id", "payload_hash"),
        Index("ix_provider_payloads_entity", "provider", "entity_type", "provider_entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    entity_type: Mapped[str] = mapped_column(String(32))  # fixture|events|competition|team|odds
    provider_entity_id: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlatformSetting(TimestampMixin, Base):
    """Admin-editable key/value configuration (scanner thresholds etc.)."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(String(255))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SyncRun(Base):
    """Background synchronisation / scanner job runs, shown as sync status."""

    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_runs_job_started", "job", "started_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(48))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(12))  # running|success|failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
