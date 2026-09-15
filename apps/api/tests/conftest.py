"""Shared pytest fixtures — a migrated `_test` database, per-test cleanup, and an ASGI test client."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

API_ROOT = Path(__file__).resolve().parent.parent


def _force_test_database_url() -> None:
    """Rewrite `DATABASE_URL` to a `_test`-suffixed database, in the environment itself, before
    `app.core.config` ever loads.

    The autouse fixture below TRUNCATEs every table after each test. Forcing a separate database
    name here makes it structurally impossible for the suite to wipe a dev stack's data, rather
    than relying on every `.env` being set up correctly.
    """
    base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://rescope:rescope@localhost:5433/rescope")
    scheme, netloc, path, query, fragment = urlsplit(base)
    db_name = path.lstrip("/")
    if not db_name.endswith("_test"):
        os.environ["DATABASE_URL"] = urlunsplit((scheme, netloc, f"/{db_name}_test", query, fragment))
    # Tests exercise RLS through the app role when one is configured, so point it at the same db.
    app_url = os.environ.get("APP_DATABASE_URL")
    if app_url:
        scheme, netloc, path, query, fragment = urlsplit(app_url)
        db_name = path.lstrip("/")
        if not db_name.endswith("_test"):
            os.environ["APP_DATABASE_URL"] = urlunsplit((scheme, netloc, f"/{db_name}_test", query, fragment))


def _force_test_redis_db_index() -> None:
    """Rewrite `REDIS_URL` to db index 15 — the autouse fixture FLUSHDBs after every test."""
    base = os.environ.get("REDIS_URL", "redis://localhost:16380/0")
    scheme, netloc, path, query, fragment = urlsplit(base)
    if path.lstrip("/") != "15":
        os.environ["REDIS_URL"] = urlunsplit((scheme, netloc, "/15", query, fragment))


async def _ensure_database_exists(url: str) -> None:
    """Create the `_test` database if it doesn't exist yet (Postgres has no CREATE DATABASE IF NOT EXISTS)."""
    scheme, netloc, path, _, _ = urlsplit(url)
    db_name = path.lstrip("/")
    admin_url = urlunsplit((scheme, netloc, "/postgres", "", "")).replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(admin_url)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()


_force_test_database_url()
_force_test_redis_db_index()
asyncio.run(_ensure_database_exists(os.environ["DATABASE_URL"]))

# Imported only after the overrides above: Settings is lru_cache'd on first call.
from app.core.db import async_session_factory, engine  # noqa: E402
from app.core.redis import close_redis, get_redis  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def apply_migrations() -> None:
    """Run Alembic against the test database once, before any test touches it."""
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, check=True)


@pytest.fixture(autouse=True)
async def clean_state() -> AsyncGenerator[None]:
    """Truncate every application table, flush Redis, and drop both connection pools after each
    test. pytest-asyncio gives every test its own event loop, but the engine and Redis client are
    module-level singletons — a connection left checked-in from this loop would fail in the next."""
    yield
    async with engine.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        tables = [row[0] for row in rows]
        if tables:
            joined = ", ".join(f'"{t}"' for t in tables)
            await conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
    await get_redis().flushdb()
    await close_redis()
    await engine.dispose()


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession]:
    """A session for tests that need to read or seed the database directly."""
    async with async_session_factory() as session:
        yield session


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """An httpx client bound to the ASGI app, with the root domain as its base URL."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://rescope.localhost") as c:
        yield c
