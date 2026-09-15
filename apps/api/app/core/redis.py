"""One Redis client per process, created lazily and shared by sessions, rate limits, and caches."""

from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide Redis client, connecting on first use."""
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


async def close_redis() -> None:
    """Drop the shared client so the next `get_redis()` reconnects — used by tests and shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
