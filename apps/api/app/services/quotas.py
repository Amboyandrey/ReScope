"""Checking a tenant's plan limits before a scrape job is enqueued — the enforcement half of the
usage ledger (app/services/usage.py) does the counting for."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceeded
from app.models import Plan, ScrapeMode, Tenant, UsageKind
from app.services.usage import count_this_month

_KIND_BY_MODE = {ScrapeMode.FAST: UsageKind.PROFILE, ScrapeMode.DEEP: UsageKind.DEEP_PROFILE}


def _limit_for(plan: Plan, kind: UsageKind) -> int:
    return plan.profiles_per_month if kind == UsageKind.PROFILE else plan.deep_runs_per_month


async def assert_within_quota(db: AsyncSession, *, tenant: Tenant, mode: ScrapeMode) -> None:
    """Raise `QuotaExceeded` if running one more job of this mode would put the tenant over its
    plan's monthly limit for that kind. Checked before enqueue, not after — a job already running
    has already been counted against the month it started in, never retroactively rejected."""
    plan = await db.get(Plan, tenant.plan_id)
    assert plan is not None  # every tenant is created with a valid plan_id (see services/tenants.py)
    kind = _KIND_BY_MODE[mode]
    used = await count_this_month(db, tenant_id=tenant.id, kind=kind)
    if used >= _limit_for(plan, kind):
        raise QuotaExceeded()


__all__ = ["assert_within_quota"]
