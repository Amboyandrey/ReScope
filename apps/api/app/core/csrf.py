"""CSRF for every mutating request — enforced in middleware so no router can forget it.

Double-submit: the JS-readable `rescope_csrf` cookie must be echoed back in `X-CSRF-Token`. It's
only checked when a session cookie is present; an unauthenticated request can't do anything
privileged, which naturally exempts login and signup. `SameSite=Lax` on the cookies is the
second layer.
"""

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.errors import CsrfTokenInvalid
from app.core.security import tokens_match

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


async def csrf_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Reject a mutating request carrying a session whose CSRF header doesn't match its cookie."""
    settings = get_settings()
    if request.method in _MUTATING and request.cookies.get(settings.session_cookie_name):
        cookie = request.cookies.get(settings.csrf_cookie_name, "")
        header = request.headers.get("x-csrf-token", "")
        if not cookie or not header or not tokens_match(cookie, header):
            err = CsrfTokenInvalid()
            return JSONResponse(status_code=err.status_code, content={"detail": err.detail})
    return await call_next(request)
