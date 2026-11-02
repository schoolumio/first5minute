"""Markets, settlement rules, bookmakers, odds, predictions and model tracking."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin, utcnow
from app.models.football import Fixture


class BettingMarket(TimestampMixin, Base):
    __tablename__ = "betting_markets"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # MARKET_A | MARKET_B
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    selection: Mapped[str] = mapped_column(String(64))  # e.g. "No goal 00:00-04:59"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SettlementRule(TimestampMixin, Base):
    """Configurable bookmaker settlement definition for the five-minute window.

    ``cutoff_seconds`` is the exclusive end of the window measured as match
    clock time in the first half: 300 means 00:00-04:59 inclusive.
    ``minute_convention`` describes how providers report minutes:
      * "ordinal" (football convention): minute 5 = 04:00-04:59
      * "elapsed": minute 5 = 05:00-05:59
    """

    __tablename__ = "settlement_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    description: Mapped[str] = mapped_column(String(255))
    cutoff_seconds: Mapped[int] = mapped_column(Integer, default=300)
    minute_convention: Mapped[str] = mapped_column(String(16), default="ordinal")
    count_own_goals: Mapped[bool] = mapped_column(Boolean, default=True)
    void_if_abandoned_before_cutoff: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class Bookmaker(TimestampMixin, Base):
    __tablename__ = "bookmakers"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(48), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    website_url: Mapped[str | None] = mapped_column(String(500))
    # Authorised referral / deep-link template, e.g. "https://book.example/event/{event_ref}?ref=xyz"
    deep_link_template: Mapped[str | None] = mapped_column(String(500))
    countries: Mapped[list] = mapped_column(JSON, default=list)
    settlement_rule_id: Mapped[int | None] = mapped_column(ForeignKey("settlement_rules.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_execution_api: Mapped[bool] = mapped_column(Boolean, default=False)
    # manual (admin-created) | provider (discovered from an odds feed, inactive until reviewed) | demo
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OddsSnapshot(Base):
    """Append-only odds observation from an odds provider (never invented)."""

    __tablename__ = "odds_snapshots"
    __table_args__ = (
        Index("ix_odds_fixture_market_time", "fixture_id", "market_id", "captured_at"),
        CheckConstraint("decimal_odds > 1.0", name="odds_gt_one"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="CASCADE"))
    bookmaker_id: Mapped[int] = mapped_column(ForeignKey("bookmakers.id", ondelete="CASCADE"))
    market_id: Mapped[int] = mapped_column(ForeignKey("betting_markets.id", ondelete="CASCADE"))
    selection: Mapped[str] = mapped_column(String(64))
    decimal_odds: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    source_provider: Mapped[str] = mapped_column(String(32))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    event_ref: Mapped[str | None] = mapped_column(String(128))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    bookmaker: Mapped[Bookmaker] = relationship(lazy="joined")
    market: Mapped[BettingMarket] = relationship(lazy="joined")


class ModelVersion(TimestampMixin, Base):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("market_code", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    market_code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(32))
    algorithm: Mapped[str] = mapped_column(String(48))  # poisson_baseline | logistic | lightgbm...
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_set_version: Mapped[str] = mapped_column(String(16))
    # uncalibrated | calibrated - outputs are labelled accordingly in the UI.
    calibration_status: Mapped[str] = mapped_column(String(16), default="uncalibrated")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64))


class ModelMetric(TimestampMixin, Base):
    __tablename__ = "model_metrics"
    __table_args__ = (Index("ix_model_metrics_model_name", "model_version_id", "metric_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"))
    evaluation: Mapped[str] = mapped_column(String(32))  # walk_forward | live
    metric_name: Mapped[str] = mapped_column(String(48))
    value: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Prediction(Base):
    """Immutable pre-kickoff prediction.

    Rows are insert-only: a database trigger rejects updates to the predictive
    fields, and a check constraint enforces ``predicted_at < kickoff_at``.
    Re-predictions insert a new row and mark the previous one superseded.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint("fixture_id", "market_code", "model_version_id", "input_data_version", "predicted_at",
                         name="fixture_market_model_inputs_at"),
        CheckConstraint("probability >= 0 AND probability <= 1", name="probability_range"),
        CheckConstraint("predicted_at < kickoff_at", name="pre_kickoff"),
        Index("ix_predictions_fixture_market_current", "fixture_id", "market_code", "is_current"),
        Index("ix_predictions_kickoff", "kickoff_at"),
        Index("uq_predictions_one_current", "fixture_id", "market_code", unique=True, postgresql_where=text("is_current")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id", ondelete="RESTRICT"))
    market_code: Mapped[str] = mapped_column(String(32))
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="RESTRICT"))
    settlement_rule_id: Mapped[int] = mapped_column(ForeignKey("settlement_rules.id", ondelete="RESTRICT"))
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kickoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_data_version: Mapped[str] = mapped_column(String(64))  # hash of inputs used
    probability: Mapped[float] = mapped_column(Float)
    lambda_home: Mapped[float | None] = mapped_column(Float)
    lambda_away: Mapped[float | None] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. P(0-0), P(1-1)...
    confidence: Mapped[str] = mapped_column(String(8))  # high|medium|low
    data_quality: Mapped[str] = mapped_column(String(16))  # high|medium|low|insufficient
    sample_home: Mapped[int] = mapped_column(Integer)
    sample_away: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(String(16))  # qualified|watchlist|below_threshold|excluded
    category_reasons: Mapped[list] = mapped_column(JSON, default=list)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    fixture: Mapped[Fixture] = relationship(lazy="joined")
    model_version: Mapped[ModelVersion] = relationship(lazy="joined")
    outcome: Mapped[PredictionOutcome | None] = relationship(back_populates="prediction", uselist=False)


class PredictionOutcome(TimestampMixin, Base):
    __tablename__ = "prediction_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id", ondelete="CASCADE"), unique=True)
    # won | lost | void | unresolved (insufficient timeline precision)
    result: Mapped[str] = mapped_column(String(12))
    home_score_at_cutoff: Mapped[int | None] = mapped_column(Integer)
    away_score_at_cutoff: Mapped[int | None] = mapped_column(Integer)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source_data_version: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(String(255))
    revision: Mapped[int] = mapped_column(Integer, default=1)  # increments if provider corrects data

    prediction: Mapped[Prediction] = relationship(back_populates="outcome")
