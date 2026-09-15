"""A sliding-window rate limiter — one atomic Redis script shared by every limited endpoint."""

import time

from redis.asyncio import Redis

# Evict entries older than the window, count what's left, admit only if under the limit — atomic,
# so concurrent requests can't race past the limit.
_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window_ms = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window_ms)
if redis.call('ZCARD', key) < limit then
    redis.call('ZADD', key, now, now .. '-' .. math.random())
    redis.call('PEXPIRE', key, window_ms)
    return 1
end
return 0
"""


async def check_rate_limit(redis: Redis, key: str, *, limit: int, window_seconds: int) -> bool:
    """Record one attempt under `key` and report whether it's within the allowed rate."""
    allowed = await redis.eval(_SCRIPT, 1, key, int(time.time() * 1000), window_seconds * 1000, limit)
    return bool(allowed)
