"""Application settings, read from environment variables / a .env file.

Nothing secret is hard-coded. In production the app refuses to start with a
missing or weak SECRET_KEY.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent
_DEV_SECRET = "dev-only-secret-change-me-dev-only-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(BACKEND_DIR / ".env"), env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "Academic Research Data Analysis Platform"
    APP_ENV: str = "development"                 # development | test | production
    API_PREFIX: str = "/api"

    # --- security ---------------------------------------------------------
    SECRET_KEY: str = _DEV_SECRET                # JWT signing key; set a random 64-char value in production
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 30
    REFRESH_TOKEN_DAYS: int = 14
    PASSWORD_RESET_MINUTES: int = 60
    EMAIL_VERIFY_HOURS: int = 48
    REQUIRE_EMAIL_VERIFICATION: bool = False     # when true, login is refused until the e-mail address is verified
    MAX_FAILED_LOGINS: int = 5
    LOCKOUT_MINUTES: int = 15
    CORS_ORIGINS: str = "http://localhost:5173"  # comma-separated list
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_AI_PER_MINUTE: int = 20

    # --- database ---------------------------------------------------------
    DATABASE_URL: str = "mysql+pymysql://research_app:change-me@127.0.0.1:3306/academic_research?charset=utf8mb4"

    # --- file storage -----------------------------------------------------
    STORAGE_BACKEND: str = "local"               # local | s3 (s3 is a documented extension point)
    STORAGE_DIR: str = str(PROJECT_DIR / "storage")
    MAX_UPLOAD_MB: int = 25
    MAX_DATASET_ROWS: int = 500_000
    MAX_DATASET_COLUMNS: int = 500

    # --- analysis jobs ----------------------------------------------------
    ANALYSIS_WORKERS: int = 2
    ANALYSIS_SYNC: bool = False                  # run jobs inline (used by tests)

    # --- AI ---------------------------------------------------------------
    AI_PROVIDER: str = "none"                    # none | openai | gemini | anthropic | local
    AI_MODEL: str = ""
    AI_API_KEY: str = ""
    AI_BASE_URL: str = ""

    # --- e-mail -----------------------------------------------------------
    FRONTEND_URL: str = "http://localhost:5173"
    SMTP_HOST: str = ""                          # empty = print e-mails to the server log (development)
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@example.org"

    @field_validator("APP_ENV")
    @classmethod
    def _env(cls, value: str) -> str:
        value = value.lower()
        if value not in ("development", "test", "production"):
            raise ValueError("APP_ENV must be development, test or production")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.APP_ENV == "production":
            if self.SECRET_KEY == _DEV_SECRET or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be set to a random value of at least 32 characters in production")
            if "change-me" in self.DATABASE_URL:
                raise ValueError("DATABASE_URL still contains the placeholder password")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
