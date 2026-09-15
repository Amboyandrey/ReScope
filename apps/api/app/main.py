"""ASGI entrypoint — builds the FastAPI app, wires middleware, and mounts the versioned routers."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.csrf import csrf_middleware
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.middleware import request_context_middleware, security_headers_middleware
from app.routers.v1 import (
    admin,
    audit,
    auth,
    companies,
    contacts,
    health,
    invitations,
    members,
    notes,
    search,
    tags,
    tenants,
)

settings = get_settings()
configure_logging(settings.debug)

app = FastAPI(title=settings.app_name, debug=settings.debug)

# Order matters: security headers wrap everything, then request context, CSRF, then CORS closest to the app.
app.middleware("http")(security_headers_middleware)
app.middleware("http")(request_context_middleware)
app.middleware("http")(csrf_middleware)
# Every tenant is a subdomain of the root domain, so tenant origins are matched by regex rather
# than enumerated — a new tenant needs no config change to call the API from its own origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=rf"^https?://([a-z0-9-]+\.)?{settings.root_domain.replace('.', r'\.')}(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1")
app.include_router(tenants.router, prefix="/api/v1")
app.include_router(members.router, prefix="/api/v1")
app.include_router(companies.router, prefix="/api/v1")
app.include_router(contacts.router, prefix="/api/v1")
app.include_router(notes.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(tags.tags_router, prefix="/api/v1")
app.include_router(tags.company_tags_router, prefix="/api/v1")
app.include_router(invitations.tenant_router, prefix="/api/v1")
app.include_router(invitations.token_router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    """Turn any domain exception into a JSON error response at its mapped status code."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/")
async def root() -> dict[str, str]:
    """Confirm the API is reachable at its base path."""
    return {"service": settings.app_name, "status": "running"}
