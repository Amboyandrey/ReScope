"""Async SQLAlchemy engine and session factory — the only place a Postgres connection pool is opened."""

import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# `app_database_url`, when set, is the low-privilege role RLS applies to; the owner role is exempt.
engine = create_async_engine(
    settings.app_database_url or settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Shared declarative base every ORM model inherits from."""


async def set_tenant_scope(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Set `app.tenant_id` for the rest of the current transaction — what every row-level
    security policy checks.

    `set_config(..., true)` is the parameterized `SET LOCAL`: transaction-scoped, so it can't leak
    into the next request when the connection returns to the pool, and it resets at the commit
    `get_db()` issues when the request finishes. Background jobs must call this again after every
    commit for the same reason.
    """
    await db.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


async def get_db() -> AsyncGenerator[AsyncSession]:
    """Yield a request-scoped session, committing on success and rolling back on error."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
