"""Import every model so Alembic autogenerate and relationships see them."""

from app.models.activity import (
    AuditLog,
    BetTracking,
    DataProviderLog,
    Notification,
    PlatformSetting,
    ProviderPayload,
    SavedMatch,
    SyncRun,
)
from app.models.football import (
    Competition,
    Fixture,
    MatchEvent,
    Season,
    Team,
    TeamFormFeature,
    TeamMatchStats,
)
from app.models.markets import (
    BettingMarket,
    Bookmaker,
    ModelMetric,
    ModelVersion,
    OddsSnapshot,
    Prediction,
    PredictionOutcome,
    SettlementRule,
)
from app.models.user import AuthToken, Invoice, Plan, Role, Subscription, User

__all__ = [
    "AuditLog",
    "AuthToken",
    "BetTracking",
    "BettingMarket",
    "Bookmaker",
    "Competition",
    "DataProviderLog",
    "Fixture",
    "Invoice",
    "MatchEvent",
    "ModelMetric",
    "ModelVersion",
    "Notification",
    "OddsSnapshot",
    "Plan",
    "PlatformSetting",
    "Prediction",
    "PredictionOutcome",
    "ProviderPayload",
    "Role",
    "SavedMatch",
    "Season",
    "SettlementRule",
    "Subscription",
    "SyncRun",
    "Team",
    "TeamFormFeature",
    "TeamMatchStats",
    "User",
]
