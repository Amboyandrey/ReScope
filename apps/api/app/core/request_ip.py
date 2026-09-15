"""The caller's IP for rate limiting — trusts `X-Forwarded-For` only in production behind our proxy."""

from fastapi import Request

from app.core.config import get_settings


def client_ip(request: Request) -> str:
    """Return the best-known client address. Behind Caddy in production the first forwarded hop is
    the client; in development there's no proxy, so the socket peer is used directly."""
    if get_settings().environment == "production":
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
