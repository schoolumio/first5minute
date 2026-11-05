"""Application configuration loaded from environment variables.

Every secret comes from the environment. Nothing sensitive is hardcoded; the
defaults below are only safe for local development and are rejected in
production by ``Settings.validate_production``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEV_SECRET = "dev-insecure-secret-change-me-0123456789abcdef"


class Settings(BaseSettings):
    # Later files win: backend/.env overrides the repo-root .env (docker-compose and the README use the root one).
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    # --- General -----------------------------------------------------------
    app_name: str = "First5Minute"
    environment: Literal["development", "test", "staging", "production"] = "development"
    api_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:3000"
    # NoDecode: accept "a,b" (comma separated) or a JSON list; the validator below does the parsing.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"
    sentry_dsn: str | None = None

    # --- Persistence -------------------------------------------------------
    database_url: str = "postgresql+psycopg://five:five@localhost:5432/projectfive"
    redis_url: str = "redis://localhost:6379/0"

    # --- Auth --------------------------------------------------------------
    secret_key: str = DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    email_token_ttl_hours: int = 24
    password_reset_ttl_minutes: int = 60
    cookie_secure: bool = False
    cookie_domain: str | None = None

    # --- Rate limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10
    rate_limit_default_per_minute: int = 120

    # --- Email -------------------------------------------------------------
    email_backend: Literal["console", "smtp", "memory"] = "console"
    email_from: str = "First5Minute <no-reply@first5minute.local>"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True

    # --- Football data -----------------------------------------------------
    football_provider: Literal["demo", "api_football", "sportmonks"] = "demo"
    # Comma-separated provider league ids to ingest (e.g. "39,140,135"). REQUIRED for real providers: without it the
    # sync would pull every competition worldwide and exhaust the API quota. Find ids with `python -m app.cli leagues`.
    football_league_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    football_allow_all_leagues: bool = False   # explicit opt-in to sync every competition (high request volume)
    api_football_key: str | None = None
    api_football_base_url: str = "https://v3.football.api-sports.io"
    # Free plan allows 10/min; paid plans allow far more (raise this in .env to download faster).
    api_football_requests_per_minute: int = 10
    sportmonks_token: str | None = None
    sportmonks_base_url: str = "https://api.sportmonks.com/v3/football"
    sportmonks_requests_per_minute: int = 50

    # --- Odds --------------------------------------------------------------
    odds_provider: Literal["none", "api_football", "demo"] = "none"

    # --- Booking code converter ---------------------------------------------
    booking_converter_enabled: bool = True
    # Local-testing simulator with fictional bookmakers; NEVER in production (see validate_production). Codes it makes are labelled DEMO.
    booking_converter_demo: bool = False
    booking_converter_timeout_seconds: float = 15.0        # per request to a bookmaker integration
    booking_converter_match_deadline_seconds: float = 45.0  # total time budget for matching one slip
    booking_converter_session_ttl_seconds: int = 900        # how long a decoded slip stays available for the next step
    booking_converter_max_selections: int = 40
    booking_converter_per_minute: int = 8                   # per user (or IP when signed out is not allowed) per minute
    booking_converter_per_hour: int = 60

    # --- Machine learning ---------------------------------------------------
    model_dir: str = "./model_store"          # joblib artifacts of trained models
    mlflow_tracking_uri: str | None = None    # e.g. sqlite:///mlflow.db or http://mlflow:5000 (unset = no tracking)
    mlflow_experiment: str = "first5minute"
    ml_min_oos_sample: int = 300              # out-of-sample settled matches required before a model may be promoted

    # --- Payments ----------------------------------------------------------
    # "demo" is a clearly-labelled local simulator (no real money, test-only; refused in production).
    payment_provider: Literal["none", "paystack", "demo"] = "none"
    paystack_secret_key: str | None = None
    paystack_base_url: str = "https://api.paystack.co"
    # Auto-renewal: charge the saved authorisation shortly before the period ends; retry on failure; keep access during grace.
    renewal_lead_hours: int = 2
    renewal_retry_hours: int = 24
    renewal_max_attempts: int = 3
    renewal_grace_days: int = 3
    renewal_reminder_days: int = 3

    @field_validator("cors_origins", "football_league_ids", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def demo_mode(self) -> bool:
        """True when no real football provider is configured."""
        return self.football_provider == "demo"

    def validate_production(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be a random value of at least 32 characters")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production (HTTPS)")
        if self.email_backend != "smtp":
            problems.append("EMAIL_BACKEND must be smtp in production")
        if self.booking_converter_demo:
            problems.append("BOOKING_CONVERTER_DEMO is a test simulator and cannot be used in production")
        if self.payment_provider == "demo":
            problems.append("PAYMENT_PROVIDER=demo is a test simulator and cannot be used in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
