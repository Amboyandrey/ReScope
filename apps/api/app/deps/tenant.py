"""The dependency chain every tenant-scoped route runs through: user -> membership -> role.

Unlike ReCore, the tenant never comes from the path — it comes from the `X-Tenant-Slug` header
the web app's proxy sets from the request's Host header (see `apps/web/proxy.ts`). A path segment
could be typed by hand to claim any tenant; a header the browser can't be tricked into changing
without also changing which origin's cookies it sends is what makes the resolution trustworthy.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header

from app.core.db import set_tenant_scope
from app.core.errors import InsufficientRole, TenantNotFound
from app.deps.auth import CurrentUser
from app.deps.db import DbSession
from app.models import Role, Tenant, User, role_at_least
from app.services.tenants import get_tenant_and_role_by_slug


@dataclass(frozen=True)
class TenantCtx:
    """Everything a tenant-scoped endpoint needs: which tenant, which user, at what role."""

    tenant: Tenant
    user: User
    role: Role


async def _tenant_slug_header(x_tenant_slug: Annotated[str | None, Header()] = None) -> str:
    """Require the `X-Tenant-Slug` header every tenant-scoped route depends on."""
    if not x_tenant_slug:
        raise TenantNotFound()
    return x_tenant_slug


async def get_tenant_ctx(
    db: DbSession, user: CurrentUser, slug: Annotated[str, Depends(_tenant_slug_header)]
) -> TenantCtx:
    """Load the caller's membership in the header's tenant, or 404 if they aren't a member."""
    tenant, role = await get_tenant_and_role_by_slug(db, slug=slug, user=user)
    # Everything this request queries from here on is scoped to this tenant — row-level security
    # on every tenant table checks exactly this, as a backstop under this membership check, not
    # instead of it (see docs/PLAN.md §3).
    await set_tenant_scope(db, tenant.id)
    return TenantCtx(tenant=tenant, user=user, role=role)


TenantContext = Annotated[TenantCtx, Depends(get_tenant_ctx)]


def require_role(minimum: Role) -> Callable[..., Awaitable[TenantCtx]]:
    """Build a dependency that raises 403 unless the caller's role meets `minimum` or higher."""

    async def check(ctx: TenantContext) -> TenantCtx:
        """Enforce the role floor this route was declared with."""
        if not role_at_least(ctx.role, minimum):
            raise InsufficientRole()
        return ctx

    return check
