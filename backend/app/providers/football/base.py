"""Football data provider abstraction and the central normalised data format.

Every adapter (API-Football, Sportmonks, demo...) converts its payloads into
these dataclasses. Nothing downstream (ingestion, engine, API) ever sees
provider-specific structures, so a provider can be added or swapped without
touching the rest of the application.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

# Normalised fixture statuses.
SCHEDULED = "scheduled"
LIVE = "live"
FINISHED = "finished"
POSTPONED = "postponed"
CANCELLED = "cancelled"
ABANDONED = "abandoned"
SUSPENDED = "suspended"
AWARDED = "awarded"

FINAL_STATUSES = {FINISHED, AWARDED}


@dataclass(slots=True)
class NormalizedCompetition:
    provider_id: str
    name: str
    country: str | None = None
    type: str = "league"
    gender: str = "men"
    logo_url: str | None = None
    season_label: str | None = None
    season_provider_id: str | None = None


@dataclass(slots=True)
class NormalizedTeam:
    provider_id: str
    name: str
    short_name: str | None = None
    country: str | None = None
    gender: str = "men"
    is_national: bool = False
    logo_url: str | None = None


@dataclass(slots=True)
class NormalizedEvent:
    """A single match event.

    ``minute`` is the provider-reported minute; ``extra_minute`` the stoppage
    time minute (e.g. 45+2 -> minute=45, extra_minute=2). ``second`` is the
    elapsed seconds within the period when the provider supplies sub-minute
    precision (otherwise None). ``team_provider_id`` is the team the event is
    attributed to by the provider (for own goals, the player's team).
    """

    type: str  # goal|card|subst|var|other
    minute: int
    team_provider_id: str | None
    detail: str | None = None  # normal|own_goal|penalty|missed_penalty|yellow|red|goal_cancelled...
    period: str = "1H"
    extra_minute: int | None = None
    second: int | None = None
    player_name: str | None = None
    provider_event_id: str | None = None
    is_cancelled: bool = False


@dataclass(slots=True)
class NormalizedFixture:
    provider_id: str
    competition: NormalizedCompetition
    home_team: NormalizedTeam
    away_team: NormalizedTeam
    kickoff_at: datetime  # timezone-aware UTC
    status: str
    provider_status: str | None = None
    round: str | None = None
    venue: str | None = None
    neutral_venue: bool = False
    actual_kickoff_at: datetime | None = None
    home_score_ft: int | None = None
    away_score_ft: int | None = None
    home_score_ht: int | None = None
    away_score_ht: int | None = None
    events: list[NormalizedEvent] | None = None  # None = events not fetched
    raw: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """Raised for unrecoverable provider failures (after retries)."""


class ProviderNotConfigured(ProviderError):
    """Raised when a provider is selected but its credentials are missing."""


class ProviderQuotaExceeded(ProviderError):
    """The provider's daily/monthly request allowance is used up. Work is resumable: try again after the reset."""


class LeagueScopeError(ProviderError):
    """A real provider is active but no league allowlist is configured (would sync every competition worldwide)."""


class FootballDataProvider(abc.ABC):
    """Interface every football data adapter implements."""

    name: str = "base"
    is_demo: bool = False

    @abc.abstractmethod
    def fixtures_by_date(self, day: date) -> list[NormalizedFixture]:
        """All fixtures scheduled on a UTC calendar day (without events)."""

    @abc.abstractmethod
    def fixture_with_events(self, provider_fixture_id: str) -> NormalizedFixture:
        """One fixture including its full event timeline."""

    events_batch_size = 1   # how many fixtures `fixtures_with_events` can fetch in one request

    def fixtures_with_events(self, provider_fixture_ids: list[str]) -> list[NormalizedFixture]:
        """Fixtures including timelines for several ids. Adapters with a bulk endpoint override this to save requests."""
        return [self.fixture_with_events(i) for i in provider_fixture_ids]

    def search_leagues(self, query: str) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.name} does not support league search")

    @abc.abstractmethod
    def team_recent_fixtures(self, provider_team_id: str, last: int = 20) -> list[NormalizedFixture]:
        """Most recent finished fixtures of a team (events may be omitted)."""

    def health_check(self) -> dict[str, Any]:
        return {"provider": self.name, "ok": True}
