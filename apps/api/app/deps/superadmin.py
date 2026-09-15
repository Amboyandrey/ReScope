"""The dependency that gates the platform-operator area — no tenant, just `users.is_superadmin`."""

from typing import Annotated

from fastapi import Depends

from app.core.errors import SuperadminRequired
from app.deps.auth import CurrentUser
from app.models import User


async def require_superadmin(user: CurrentUser) -> User:
    """403, not 404: `/admin/*` isn't tenant data whose existence needs hiding, it's a fixed set
    of platform routes — the caller just isn't allowed to use them."""
    if not user.is_superadmin:
        raise SuperadminRequired()
    return user


SuperadminUser = Annotated[User, Depends(require_superadmin)]
