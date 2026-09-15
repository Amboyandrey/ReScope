"""Application settings, loaded once from the environment and shared everywhere via `get_settings`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed, validated environment configuration for the API and worker processes."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ReScope API"
    environment: str = Field(default="development")
    debug: bool = Field(default=False)

    # Owner role URL (postgresql+asyncpg://...) — owns the schema and is the only URL Alembic uses.
    database_url: str = Field(default="postgresql+asyncpg://rescope:rescope@localhost:5433/rescope")

    # The role the running API/worker serves requests through. Falls back to `database_url`. Set
    # to the low-privilege `rescope_app` role (created by the RLS migration) and row-level
    # security policies actually apply instead of being bypassed by the table owner.
    app_database_url: str | None = Field(default=None)

    db_pool_size: int = 10
    db_max_overflow: int = 10

    # Sessions, rate limits, the arq job queue, and caches
    redis_url: str = Field(default="redis://localhost:16380/0")

    # The root domain tenants are subdomains of; also the session cookie's `Domain` (with a
    # leading dot) so one login carries across every tenant the user belongs to.
    root_domain: str = Field(default="rescope.localhost")

    # Origins allowed to call the API with credentials. The wildcard tenant origins are added at
    # runtime from `root_domain` (see main.py) — this list is for anything extra.
    cors_origins: list[str] = Field(default_factory=lambda: ["http://rescope.localhost:3000"])

    session_cookie_name: str = "rescope_session"
    csrf_cookie_name: str = "rescope_csrf"
    # Sliding TTL — refreshed on every authenticated request
    session_ttl_seconds: int = 60 * 60 * 24 * 14

    # Login/signup attempts allowed per window, per IP and per email, before a 429
    auth_rate_limit_max: int = 5
    auth_rate_limit_window_seconds: int = 300

    # Platform-paid LLM key for profiling. Read from the environment only; never persisted.
    anthropic_api_key: str = Field(default="")


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings instance, constructed once and cached."""
    return Settings()
