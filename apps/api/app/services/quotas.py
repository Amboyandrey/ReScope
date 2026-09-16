"""Checking a tenant's plan limits before a scrape job is enqueued — the enforcement half of the
usage ledger (app/services/usage.py) does the counting for."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ChatQuotaExceeded, QuotaExceeded
from app.models import Plan, ScrapeMode, Tenant, UsageKind
from app.services.llm import has_own_anthropic_key
from app.services.usage import count_this_month

# A DEEP-mode job counts against `deep_runs_per_month` regardless of which Tier 2 provider ran it
# — the custom agent (DEEP_PROFILE) and Browser Use Cloud (BROWSER_USE_RUN, docs/PLAN.md §13)
# share one ceiling, so a tenant can't double it by splitting runs across providers.
_KIND_BY_MODE: dict[ScrapeMode, UsageKind | tuple[UsageKind, ...]] = {
    ScrapeMode.FAST: UsageKind.PROFILE,
    ScrapeMode.DEEP: (UsageKind.DEEP_PROFILE, UsageKind.BROWSER_USE_RUN),
}


def _limit_for(plan: Plan, mode: ScrapeMode) -> int:
    return plan.profiles_per_month if mode == ScrapeMode.FAST else plan.deep_runs_per_month


async def assert_within_quota(db: AsyncSession, *, tenant: Tenant, mode: ScrapeMode) -> None:
    """Raise `QuotaExceeded` if running one more job of this mode would put the tenant over its
    plan's monthly limit for that kind. Checked before enqueue, not after — a job already running
    has already been counted against the month it started in, never retroactively rejected.

    A tenant running on its own Anthropic key (docs/PLAN.md §12) is exempt — the platform isn't
    paying for the call, so the platform's own plan ceiling doesn't apply. Usage is still recorded
    (`services/usage.py`'s `billed_to`), just not counted against this limit.
    """
    if await has_own_anthropic_key(db, tenant_id=tenant.id):
        return
    plan = await db.get(Plan, tenant.plan_id)
    assert plan is not None  # every tenant is created with a valid plan_id (see services/tenants.py)
    kind = _KIND_BY_MODE[mode]
    used = await count_this_month(db, tenant_id=tenant.id, kind=kind)
    if used >= _limit_for(plan, mode):
        raise QuotaExceeded()


async def assert_within_chat_quota(db: AsyncSession, *, tenant: Tenant) -> None:
    """Raise `ChatQuotaExceeded` if sending one more chat message would put the tenant over its
    plan's monthly limit — same BYOK exemption as `assert_within_quota` (docs/PLAN.md §12)."""
    if await has_own_anthropic_key(db, tenant_id=tenant.id):
        return
    plan = await db.get(Plan, tenant.plan_id)
    assert plan is not None
    used = await count_this_month(db, tenant_id=tenant.id, kind=UsageKind.CHAT)
    if used >= plan.chat_messages_per_month:
        raise ChatQuotaExceeded()


__all__ = ["assert_within_chat_quota", "assert_within_quota"]
