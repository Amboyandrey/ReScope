"""Platform-operator reads and actions — every tenant, not just the caller's own.

`tenants` itself carries no RLS (see docs/PLAN.md §3 and migration 0002's own docstring), so
listing every tenant needs no special access. Each tenant's *usage*, though, lives in an
RLS-gated table — rather than adding a second, RLS-bypassing database role just for this one
admin read, this scopes to each tenant in turn and asks its own usage ledger, the same tenant
context any regular request would set. One query per tenant, fine at the scale a platform
operator's own dashboard needs.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.errors import AppError, TenantNotFound
from app.models import Membership, Plan, Tenant
from app.services.usage import sum_cost_this_month


class PlanNotFound(AppError):
    status_code = 404
    detail = "Plan not found."


@dataclass(frozen=True)
class TenantSummary:
    tenant: Tenant
    plan_name: str
    member_count: int
    spend_this_month_usd: float


async def list_tenants_with_usage(db: AsyncSession) -> list[TenantSummary]:
    """Every tenant on the platform, with its plan name, member count, and this month's spend."""
    tenants = list((await db.scalars(select(Tenant).order_by(Tenant.created_at.desc()))).all())
    plans = {p.id: p for p in (await db.scalars(select(Plan))).all()}

    summaries = []
    for tenant in tenants:
        await set_tenant_scope(db, tenant.id)
        member_ids = await db.scalars(select(Membership.user_id).where(Membership.tenant_id == tenant.id))
        member_count = len(list(member_ids.all()))
        spend = await sum_cost_this_month(db, tenant_id=tenant.id)
        summaries.append(
            TenantSummary(
                tenant=tenant,
                plan_name=plans[tenant.plan_id].name,
                member_count=member_count,
                spend_this_month_usd=spend,
            )
        )
    return summaries


async def change_tenant_plan(db: AsyncSession, *, tenant_id: uuid.UUID, plan_id: str) -> Tenant:
    """Move a tenant onto a different plan, effective immediately (their quotas next check
    against the new plan's own limits — nothing about usage already recorded changes)."""
    plan = await db.get(Plan, plan_id)
    if plan is None:
        raise PlanNotFound()
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise TenantNotFound()
    tenant.plan_id = plan_id
    await db.flush()
    return tenant
