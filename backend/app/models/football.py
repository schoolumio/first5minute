"""Football domain: competitions, teams, fixtures and match events.

Internal integer IDs are never shared with providers. Each entity keeps the
originating ``provider`` and ``provider_id`` in separate columns, unique per
provider, so re-ingestion is idempotent and multiple providers can coexist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class Competition(TimestampMixin, Base):
    __tablename__ = "competitions"
    __table_args__ = (UniqueConstraint("provider", "provider_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160))
    country: Mapped[str | None] = mapped_column(String(80))
    type: Mapped[str] = mapped_column(String(24), default="league")  # league|cup|international|continental
    gender: Mapped[str] = mapped_column(String(8), default="men")  # men|women
    logo_url: Mapped[str | None] = mapped_column(String(500))
    # Admin-controlled eligibility for scanning.
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    data_quality_tier: Mapped[str] = mapped_column(String(8), default="unknown")  # high|medium|low|unknown
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    seasons: Mapped[list[Season]] = relationship(back_populates="competition")


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("competition_id", "label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"))
    provider_id: Mapped[str | None] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(32))  # e.g. "2025/26" or "2026"
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)

    competition: Mapped[Competition] = relationship(back_populates="seasons")


class Team(TimestampMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("provider", "provider_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(160), index=True)
    short_name: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(80))
    gender: Mapped[str] = mapped_column(String(8), default="men")
    is_national: Mapped[bool] = mapped_column(Boolean, default=False)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Fixture(TimestampMixin, Base):
    __tablename__ = "fixtures"
    __table_args__ = (
        UniqueConstraint("provider", "provider_id"),
        Index("ix_fixtures_kickoff", "kickoff_at"),
        Index("ix_fixtures_home_kickoff", "home_team_id", "kickoff_at"),
        Index("ix_fixtures_away_kickoff", "away_team_id", "kickoff_at"),
        Index("ix_fixtures_competition_kickoff", "competition_id", "kickoff_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_id: Mapped[str] = mapped_column(String(64))
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="RESTRICT"))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id", ondelete="SET NULL"))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="RESTRICT"))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # scheduled, UTC
    actual_kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Normalised status: scheduled|live|finished|postponed|cancelled|abandoned|suspended|awarded
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    provider_status: Mapped[str | None] = mapped_column(String(16))
    round: Mapped[str | None] = mapped_column(String(80))
    venue: Mapped[str | None] = mapped_column(String(160))
    neutral_venue: Mapped[bool] = mapped_column(Boolean, default=False)
    home_score_ft: Mapped[int | None] = mapped_column(SmallInteger)
    away_score_ft: Mapped[int | None] = mapped_column(SmallInteger)
    home_score_ht: Mapped[int | None] = mapped_column(SmallInteger)
    away_score_ht: Mapped[int | None] = mapped_column(SmallInteger)
    # Event-timeline completeness: whether goal events reconcile with the score.
    events_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timeline_status: Mapped[str] = mapped_column(String(16), default="missing")  # complete|inconsistent|missing
    timeline_precision: Mapped[str | None] = mapped_column(String(8))  # second|minute
    data_version: Mapped[int] = mapped_column(Integer, default=1)  # bumps whenever events/score change
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    competition: Mapped[Competition] = relationship(lazy="joined")
    season: Mapped[Season | None] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id], lazy="joined")
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id], lazy="joined")
    events: Mapped[list[MatchEvent]] = relationship(
        back_populates="fixture", cascade="all, delete-orphan", order_by="MatchEvent.sort_key"
    )


class MatchEvent(TimestampMixin, Base):
    """A normalised match event (goal, card, substitution, VAR...)."""

    __tablename__ = "match_events"
    __table_args__ = (
        UniqueConstraint("fixture_id", "event_key"),
        Index("ix_match_events_fixture_type", "fixture_id", "type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"))
    # Deterministic dedup key: provider event id, or a hash of its content.
    event_key: Mapped[str] = mapped_column(String(96))
    type: Mapped[str] = mapped_column(String(16))  # goal|card|subst|var|other
    detail: Mapped[str | None] = mapped_column(String(64))  # normal|own_goal|penalty|missed_penalty|red|yellow...
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    # Team credited with the goal (differs from team_id for own goals).
    scoring_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    player_name: Mapped[str | None] = mapped_column(String(160))
    period: Mapped[str] = mapped_column(String(8), default="1H")  # 1H|2H|ET|PEN
    minute: Mapped[int] = mapped_column(SmallInteger)  # ordinal minute as reported (1..90+)
    extra_minute: Mapped[int | None] = mapped_column(SmallInteger)  # stoppage time minute
    second: Mapped[int | None] = mapped_column(SmallInteger)  # elapsed seconds in the period, if provider supplies it
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)  # VAR-disallowed / provider-corrected
    sort_key: Mapped[int] = mapped_column(Integer, default=0)

    fixture: Mapped[Fixture] = relationship(back_populates="events")


class TeamMatchStats(TimestampMixin, Base):
    """Per-team, per-fixture derived early-goal statistics (one row per side)."""

    __tablename__ = "team_match_stats"
    __table_args__ = (
        UniqueConstraint("fixture_id", "team_id"),
        Index("ix_team_match_stats_team_kickoff", "team_id", "kickoff_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    opponent_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id", ondelete="CASCADE"))
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_home: Mapped[bool] = mapped_column(Boolean)
    goals_for: Mapped[int] = mapped_column(SmallInteger)
    goals_against: Mapped[int] = mapped_column(SmallInteger)
    early_goals_for: Mapped[int] = mapped_column(SmallInteger)  # within settlement window
    early_goals_against: Mapped[int] = mapped_column(SmallInteger)
    first_goal_minute: Mapped[int | None] = mapped_column(SmallInteger)  # first goal of the match (either side)
    red_card_early: Mapped[bool] = mapped_column(Boolean, default=False)
    settlement_rule_code: Mapped[str] = mapped_column(String(32))
    reliable: Mapped[bool] = mapped_column(Boolean, default=True)
    source_data_version: Mapped[int] = mapped_column(Integer, default=1)


class TeamFormFeature(TimestampMixin, Base):
    """Snapshot of pre-kickoff features used for a prediction (audit + training)."""

    __tablename__ = "team_form_features"
    __table_args__ = (UniqueConstraint("fixture_id", "team_id", "feature_set_version", "as_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    feature_set_version: Mapped[str] = mapped_column(String(16))
    sample_size: Mapped[int] = mapped_column(Integer)
    features: Mapped[dict] = mapped_column(JSON)
    early_scoring_rate: Mapped[float | None] = mapped_column(Float)
    early_conceding_rate: Mapped[float | None] = mapped_column(Float)
