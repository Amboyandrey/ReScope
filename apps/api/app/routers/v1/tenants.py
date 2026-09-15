"""Creating a tenant and listing the ones the caller belongs to."""

from fastapi import APIRouter, status

from app.deps.auth import CurrentUser
from app.deps.db import DbSession
from app.deps.tenant import TenantContext
from app.schemas.tenant import CreateTenantRequest, MyTenantResponse, TenantResponse
from app.services.audit import record_audit
from app.services.tenants import create_tenant, list_my_tenants

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create(body: CreateTenantRequest, user: CurrentUser, db: DbSession) -> TenantResponse:
    """Create a tenant and make the caller its owner."""
    tenant = await create_tenant(db, owner=user, name=body.name, slug=body.slug)
    await record_audit(
        db,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="tenant.created",
        target_type="tenant",
        target_id=str(tenant.id),
    )
    return TenantResponse.model_validate(tenant)


@router.get("", response_model=list[MyTenantResponse])
async def list_mine(user: CurrentUser, db: DbSession) -> list[MyTenantResponse]:
    """List every tenant the caller belongs to, with their role in each."""
    pairs = await list_my_tenants(db, user=user)
    return [MyTenantResponse(**TenantResponse.model_validate(t).model_dump(), role=r) for t, r in pairs]


@router.get("/current", response_model=TenantResponse)
async def current(ctx: TenantContext) -> TenantResponse:
    """Return the tenant named by the caller's `X-Tenant-Slug` header."""
    return TenantResponse.model_validate(ctx.tenant)
