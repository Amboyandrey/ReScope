"""Liveness and readiness — readiness actually round-trips Postgres and Redis."""

from fastapi import APIRouter
from sqlalchemy import text

from app.core.redis import get_redis
from app.deps.db import DbSession

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Report that the process is up; does not touch any dependency."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(db: DbSession) -> dict[str, str]:
    """Report that the process can reach both Postgres and Redis."""
    await db.execute(text("SELECT 1"))
    await get_redis().ping()
    return {"status": "ready"}
