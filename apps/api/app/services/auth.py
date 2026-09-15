"""Signup, login and logout — takes plain arguments, returns models, raises domain errors."""

import uuid

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import EmailAlreadyRegistered, InvalidCredentials, RateLimited
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.services.rate_limit import check_rate_limit
from app.services.sessions import create_session, delete_session

settings = get_settings()


async def _enforce_auth_rate_limit(redis: Redis, *, ip: str, email: str) -> None:
    """Both the caller's IP and the targeted email are limited — one attacker, many emails, or
    many attackers, one email, both get caught."""
    limit, window = settings.auth_rate_limit_max, settings.auth_rate_limit_window_seconds
    ip_ok = await check_rate_limit(redis, f"ratelimit:auth:ip:{ip}", limit=limit, window_seconds=window)
    email_ok = await check_rate_limit(
        redis, f"ratelimit:auth:email:{email}", limit=limit, window_seconds=window
    )
    if not (ip_ok and email_ok):
        raise RateLimited()


async def signup(
    db: AsyncSession, redis: Redis, *, email: str, password: str, display_name: str, ip: str
) -> tuple[User, str, str]:
    """Create an account and sign it in. Returns (user, session_id, csrf_token)."""
    email = email.strip().lower()
    await _enforce_auth_rate_limit(redis, ip=ip, email=email)
    existing = await db.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        raise EmailAlreadyRegistered()
    user = User(email=email, password_hash=hash_password(password), display_name=display_name.strip())
    db.add(user)
    await db.flush()
    session_id, csrf_token = await create_session(redis, user.id)
    return user, session_id, csrf_token


async def login(
    db: AsyncSession, redis: Redis, *, email: str, password: str, ip: str
) -> tuple[User, str, str]:
    """Verify credentials and start a session. Returns (user, session_id, csrf_token)."""
    email = email.strip().lower()
    await _enforce_auth_rate_limit(redis, ip=ip, email=email)
    user = await db.scalar(select(User).where(User.email == email))
    # Verify against a dummy hash when the user is unknown so timing doesn't reveal which emails exist.
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise InvalidCredentials()
    if not verify_password(password, user.password_hash):
        raise InvalidCredentials()
    session_id, csrf_token = await create_session(redis, user.id)
    return user, session_id, csrf_token


async def logout(redis: Redis, session_id: str) -> None:
    """End the calling session."""
    await delete_session(redis, session_id)


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Fetch a user by id, or None if it was deleted since the session was issued."""
    return await db.get(User, user_id)


_DUMMY_HASH = hash_password("not-a-real-password")
