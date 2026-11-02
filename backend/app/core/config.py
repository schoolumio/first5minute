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
    api_football_key: str | None = None
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_football_requests_per_minute: int = 30
    sportmonks_token: str | None = None
    sportmonks_base_url: str = "https://api.sportmonks.com/v3/football"
    sportmonks_requests_per_minute: int = 50

    # --- Odds --------------------------------------------------------------
    odds_provider: Literal["none", "api_football"] = "none"

    # --- Machine learning ---------------------------------------------------
    model_dir: str = "./model_store"          # joblib artifacts of trained models
    mlflow_tracking_uri: str | None = None    # e.g. sqlite:///mlflow.db or http://mlflow:5000 (unset = no tracking)
    mlflow_experiment: str = "first5minute"
    ml_min_oos_sample: int = 300              # out-of-sample settled matches required before a model may be promoted

    # --- Payments ----------------------------------------------------------
    payment_provider: Literal["none", "paystack"] = "none"
    paystack_secret_key: str | None = None
    paystack_base_url: str = "https://api.paystack.co"

    @field_validator("cors_origins", mode="before")
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
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_production()
    return settings
