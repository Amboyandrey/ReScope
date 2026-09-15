"""Redis-backed sessions — the opaque cookie value is a key into this store, never a JWT.

Revoking is a `DEL`. A per-user index makes "sign out everywhere" (and removing a user) one call.
"""

import uuid
from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.security import generate_token

settings = get_settings()


def _key(session_id: str) -> str:
    return f"session:{session_id}"


def _user_index(user_id: uuid.UUID) -> str:
    return f"user_sessions:{user_id}"


@dataclass(frozen=True)
class SessionData:
    """Which user a session belongs to, and the CSRF token paired with it."""

    user_id: uuid.UUID
    csrf_token: str


async def create_session(redis: Redis, user_id: uuid.UUID) -> tuple[str, str]:
    """Start a session and return its (session_id, csrf_token) pair."""
    session_id = generate_token()
    csrf_token = generate_token()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(_key(session_id), mapping={"user_id": str(user_id), "csrf_token": csrf_token})
        pipe.expire(_key(session_id), settings.session_ttl_seconds)
        pipe.sadd(_user_index(user_id), session_id)
        pipe.expire(_user_index(user_id), settings.session_ttl_seconds)
        await pipe.execute()
    return session_id, csrf_token


async def get_session(redis: Redis, session_id: str) -> SessionData | None:
    """Look a session up and slide its expiry forward, or None if it doesn't exist."""
    data = await redis.hgetall(_key(session_id))
    if not data:
        return None
    await redis.expire(_key(session_id), settings.session_ttl_seconds)
    # decode_responses=True makes these str at runtime; redis-py's stubs can't express that.
    return SessionData(user_id=uuid.UUID(str(data["user_id"])), csrf_token=str(data["csrf_token"]))


async def delete_session(redis: Redis, session_id: str) -> None:
    """End one session immediately."""
    data = await redis.hgetall(_key(session_id))
    await redis.delete(_key(session_id))
    if data:
        await redis.srem(_user_index(uuid.UUID(str(data["user_id"]))), session_id)


async def delete_all_sessions(redis: Redis, user_id: uuid.UUID) -> None:
    """End every session a user has — sign out everywhere."""
    ids = await redis.smembers(_user_index(user_id))
    if ids:
        await redis.delete(*[_key(str(s)) for s in ids])
    await redis.delete(_user_index(user_id))
