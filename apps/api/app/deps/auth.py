"""The first link of the dependency chain: cookie → session → user."""

import uuid
from typing import Annotated

import structlog
from fastapi import Depends, Request
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import SessionInvalid
from app.core.redis import get_redis
from app.deps.db import DbSession
from app.models.user import User
from app.services.auth import get_user
from app.services.sessions import get_session

settings = get_settings()


def redis_dep() -> Redis:
    return get_redis()


RedisClient = Annotated[Redis, Depends(redis_dep)]


async def get_session_id(request: Request) -> str:
    """The raw session id from the cookie, or 401 if there isn't one."""
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        raise SessionInvalid()
    return session_id


async def get_current_user(
    db: DbSession, redis: RedisClient, session_id: Annotated[str, Depends(get_session_id)]
) -> User:
    """Resolve the session to a live user, binding the user id to the log context and to the
    `app.user_id` GUC (which the memberships RLS policy reads)."""
    session = await get_session(redis, session_id)
    if session is None:
        raise SessionInvalid()
    user = await get_user(db, session.user_id)
    if user is None:
        raise SessionInvalid()
    await db.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user.id)})
    structlog.contextvars.bind_contextvars(user_id=str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
SessionId = Annotated[str, Depends(get_session_id)]


def is_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
