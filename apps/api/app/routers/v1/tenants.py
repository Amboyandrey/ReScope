"""Creating a tenant and listing the ones the caller belongs to."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps.auth import CurrentUser
from app.deps.db import DbSession
from app.deps.tenant import TenantContext, TenantCtx, require_role
from app.models import Role
from app.schemas.tenant import (
    CreateTenantRequest,
    MyTenantResponse,
    SetChatModelRequest,
    SetScrapeProviderRequest,
    TenantResponse,
)
from app.services.audit import record_audit
from app.services.tenants import create_tenant, list_my_tenants, set_chat_model, set_scrape_provider

router = APIRouter(prefix="/tenants", tags=["tenants"])

_AdminCtx = Annotated[TenantCtx, Depends(require_role(Role.ADMIN))]


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


@router.put("/current/scrape-provider", response_model=TenantResponse)
async def set_provider(body: SetScrapeProviderRequest, ctx: _AdminCtx, db: DbSession) -> TenantResponse:
    """Switch which Tier 2 provider this tenant's deep-mode jobs use."""
    tenant = await set_scrape_provider(db, tenant=ctx.tenant, provider=body.provider)
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="tenant.scrape_provider_changed",
        target_type="tenant",
        target_id=str(ctx.tenant.id),
        metadata={"provider": body.provider.value},
    )
    return TenantResponse.model_validate(tenant)


@router.put("/current/chat-model", response_model=TenantResponse)
async def set_chat(body: SetChatModelRequest, ctx: _AdminCtx, db: DbSession) -> TenantResponse:
    """Switch which provider and model answer this tenant's chat messages."""
    tenant = await set_chat_model(db, tenant=ctx.tenant, provider=body.provider, model=body.model)
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="tenant.chat_model_changed",
        target_type="tenant",
        target_id=str(ctx.tenant.id),
        metadata={"provider": body.provider.value, "model": body.model},
    )
    return TenantResponse.model_validate(tenant)
