"""The platform-operator area: every tenant's own plan and spend, and platform-wide controls.

Every route here is gated by `require_superadmin`, never by tenant membership — there is no
`X-Tenant-Slug` header on any of these, by design.
"""

import uuid

import structlog
from fastapi import APIRouter
from sqlalchemy import select

from app.core.db import set_tenant_scope
from app.deps.db import DbSession
from app.deps.superadmin import SuperadminUser
from app.models import Plan
from app.schemas.admin import (
    ChangeTenantPlanRequest,
    PlanResponse,
    PlatformSettingsResponse,
    TenantSummaryResponse,
    UpdatePlatformSettingsRequest,
)
from app.services.admin import change_tenant_plan, list_tenants_with_usage
from app.services.audit import record_audit
from app.services.platform_settings import get_platform_settings, set_scraping_paused

logger = structlog.get_logger()

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/tenants", response_model=list[TenantSummaryResponse])
async def list_tenants(admin: SuperadminUser, db: DbSession) -> list[TenantSummaryResponse]:
    """Every tenant on the platform, with its plan and this month's spend."""
    del admin  # only needed to enforce the dependency
    summaries = await list_tenants_with_usage(db)
    return [
        TenantSummaryResponse(
            id=s.tenant.id,
            slug=s.tenant.slug,
            name=s.tenant.name,
            plan_id=s.tenant.plan_id,
            plan_name=s.plan_name,
            status=s.tenant.status,
            member_count=s.member_count,
            spend_this_month_usd=s.spend_this_month_usd,
            created_at=s.tenant.created_at,
        )
        for s in summaries
    ]


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(admin: SuperadminUser, db: DbSession) -> list[PlanResponse]:
    """Every plan a tenant could be moved onto."""
    del admin
    plans = await db.scalars(select(Plan).order_by(Plan.id))
    return [PlanResponse.model_validate(p) for p in plans]


@router.patch("/tenants/{tenant_id}/plan", response_model=TenantSummaryResponse)
async def change_plan(
    tenant_id: uuid.UUID, body: ChangeTenantPlanRequest, admin: SuperadminUser, db: DbSession
) -> TenantSummaryResponse:
    """Move a tenant onto a different plan, effective immediately."""
    tenant = await change_tenant_plan(db, tenant_id=tenant_id, plan_id=body.plan_id)
    # None of these admin routes run through get_tenant_ctx (there's no X-Tenant-Slug header on
    # a platform-wide route), so app.tenant_id was never set on this connection — without this,
    # the audit insert's own RETURNING would fail its RLS SELECT policy, the same interaction
    # the invitation-accept flow hits for the same reason (see app/routers/v1/invitations.py).
    await set_tenant_scope(db, tenant.id)
    await record_audit(
        db,
        tenant_id=tenant.id,
        actor_id=admin.id,
        action="admin.tenant_plan_changed",
        target_type="tenant",
        target_id=str(tenant.id),
        metadata={"plan_id": body.plan_id},
    )
    summaries = await list_tenants_with_usage(db)
    matched = next(s for s in summaries if s.tenant.id == tenant.id)
    return TenantSummaryResponse(
        id=matched.tenant.id,
        slug=matched.tenant.slug,
        name=matched.tenant.name,
        plan_id=matched.tenant.plan_id,
        plan_name=matched.plan_name,
        status=matched.tenant.status,
        member_count=matched.member_count,
        spend_this_month_usd=matched.spend_this_month_usd,
        created_at=matched.tenant.created_at,
    )


@router.get("/settings", response_model=PlatformSettingsResponse)
async def get_settings_route(admin: SuperadminUser, db: DbSession) -> PlatformSettingsResponse:
    del admin
    return PlatformSettingsResponse.model_validate(await get_platform_settings(db))


@router.patch("/settings", response_model=PlatformSettingsResponse)
async def update_settings(
    body: UpdatePlatformSettingsRequest, admin: SuperadminUser, db: DbSession
) -> PlatformSettingsResponse:
    """Flip the scraping killswitch — the one lever that pauses every tenant's scraping at once.

    Logged via structlog, not the tenant-scoped `audit_logs` table: `audit_logs.tenant_id` is
    `NOT NULL` by design (every other audited action in this app genuinely has one), and this
    action, unlike a plan change, has none — it isn't about any single tenant.
    """
    settings = await set_scraping_paused(db, paused=body.scraping_paused)
    logger.info("admin.scraping_paused_changed", actor_id=str(admin.id), scraping_paused=body.scraping_paused)
    return PlatformSettingsResponse.model_validate(settings)
