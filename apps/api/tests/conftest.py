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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

API_ROOT = Path(__file__).resolve().parent.parent


def _with_test_db_name(url: str) -> str:
    scheme, netloc, path, query, fragment = urlsplit(url)
    db_name = path.lstrip("/")
    if not db_name.endswith("_test"):
        path = f"/{db_name}_test"
    return urlunsplit((scheme, netloc, path, query, fragment))


def _force_test_database_urls() -> None:
    """Rewrite `DATABASE_URL` to a `_test`-suffixed database, in the environment itself, before
    `app.core.config` ever loads — and point `APP_DATABASE_URL` at the low-privilege role on that
    same database.

    The autouse fixture below TRUNCATEs every table after each test. Forcing a separate database
    name makes it structurally impossible for the suite to wipe a dev stack's data. Running the
    app under `rescope_app` (the role the RLS migration creates) means the suite exercises
    row-level security for real instead of as the RLS-exempt owner.
    """
    base = os.environ.get("DATABASE_URL", "postgresql+asyncpg://rescope:rescope@localhost:5433/rescope")
    os.environ["DATABASE_URL"] = _with_test_db_name(base)
    scheme, netloc, path, query, fragment = urlsplit(os.environ["DATABASE_URL"])
    host = netloc.rsplit("@", 1)[-1]
    os.environ["APP_DATABASE_URL"] = urlunsplit(
        (scheme, f"rescope_app:rescope_app_dev_only@{host}", path, query, fragment)
    )


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


_force_test_database_urls()
_force_test_redis_db_index()
asyncio.run(_ensure_database_exists(os.environ["DATABASE_URL"]))

# Imported only after the overrides above: Settings is lru_cache'd on first call.
from app.core.config import get_settings  # noqa: E402
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
    module-level singletons — a connection left checked-in from this loop would fail in the next.

    `plans` and `platform_settings` are deliberately NOT truncated: both are seed reference data a
    migration inserts once (`0002` and `0005` respectively), and `apply_migrations` only runs
    `alembic upgrade head` once per session — truncating either here would permanently empty it
    for every test after the first, since there's no migration left to reseed it once the database
    is already at head. `platform_settings` is a single mutable row rather than a static table
    though, so a test that flips the killswitch resets it by UPDATE instead, the same durable-row
    treatment ReCore's own feature_flags exclusion gets."""
    yield
    # Truncation needs the owner role: the app role has CRUD only, and RLS would hide rows anyway.
    owner = create_async_engine(get_settings().database_url, poolclass=NullPool)
    async with owner.begin() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename NOT IN ('alembic_version', 'plans', 'platform_settings')"
            )
        )
        tables = [row[0] for row in rows]
        if tables:
            joined = ", ".join(f'"{t}"' for t in tables)
            await conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
        await conn.execute(text("UPDATE platform_settings SET scraping_paused = false"))
    await owner.dispose()
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
    """An httpx client bound to the ASGI app at the API's own subdomain of the root domain, so
    the `Domain=.rescope.localhost` cookies the API issues are accepted and sent back."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://api.rescope.localhost") as c:
        yield c
