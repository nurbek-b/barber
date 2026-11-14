from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings. All secrets come from the environment, never from code."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Environment = Environment.DEV
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://localhost:5432/barber"
    database_pool_size: int = 10
    database_echo: bool = False
    redis_url: str = "redis://localhost:6379/0"

    # Telegram
    bot_token: SecretStr = SecretStr("")
    bot_username: str = ""
    miniapp_short_name: str = "app"
    webhook_secret: SecretStr = SecretStr("")
    init_data_ttl_seconds: int = 24 * 3600
    miniapp_url: str = ""  # https URL of the Mini App (WebApp buttons, menu button)
    staff_link_ttl_seconds: int = 7 * 24 * 3600

    # Admin auth
    jwt_secret: SecretStr = SecretStr("")
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 30 * 24 * 3600
    cookie_secure: bool = True
    cookie_domain: str | None = None
    login_rate_limit_per_minute: int = 5

    # HTTP
    cors_origins: list[str] = Field(default_factory=list)
    public_base_url: str = "http://localhost:8000"
    media_dir: str = "./media"
    media_url_prefix: str = "/media"
    max_upload_bytes: int = 5 * 1024 * 1024

    sentry_dsn: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_dev(self) -> bool:
        return self.env in (Environment.DEV, Environment.TEST)

    def validate_for_runtime(self) -> None:
        """Fail fast in non-dev environments when required secrets are missing."""
        if self.is_dev:
            return
        missing = [
            name
            for name, secret in (
                ("BOT_TOKEN", self.bot_token),
                ("WEBHOOK_SECRET", self.webhook_secret),
                ("JWT_SECRET", self.jwt_secret),
            )
            if not secret.get_secret_value()
        ]
        if missing:
            raise RuntimeError(f"Missing required settings: {', '.join(missing)}")
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters")


@lru_cache
def get_settings() -> Settings:
    return Settings()
