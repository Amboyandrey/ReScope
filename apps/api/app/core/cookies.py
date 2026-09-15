"""Setting and clearing the session + CSRF cookie pair, scoped to the root domain.

`Domain=.<root>` is what lets one login carry across every tenant subdomain. `Secure` is dropped
only in development, where the app runs over plain http on `*.localhost`.
"""

from fastapi import Response

from app.core.config import get_settings

settings = get_settings()


def _secure() -> bool:
    return settings.environment != "development"


def set_auth_cookies(response: Response, session_id: str, csrf_token: str) -> None:
    """Issue the httpOnly session cookie and the JS-readable CSRF cookie (double-submit pattern)."""
    common = {
        "domain": f".{settings.root_domain}",
        "path": "/",
        "secure": _secure(),
        "samesite": "lax",
        "max_age": settings.session_ttl_seconds,
    }
    response.set_cookie(settings.session_cookie_name, session_id, httponly=True, **common)  # type: ignore[arg-type]
    response.set_cookie(settings.csrf_cookie_name, csrf_token, httponly=False, **common)  # type: ignore[arg-type]


def clear_auth_cookies(response: Response) -> None:
    """Expire both cookies on the same domain/path they were set on — anything else is ignored."""
    for name in (settings.session_cookie_name, settings.csrf_cookie_name):
        response.delete_cookie(name, domain=f".{settings.root_domain}", path="/")
