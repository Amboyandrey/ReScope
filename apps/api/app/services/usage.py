"""Recording and reading the usage ledger — one row per billable scrape-job step."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent, UsageKind


async def record_usage_event(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    kind: UsageKind,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> UsageEvent:
    """Append one row. Callers never update or delete it afterward."""
    event = UsageEvent(
        tenant_id=tenant_id,
        job_id=job_id,
        kind=kind,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
    )
    db.add(event)
    await db.flush()
    return event


def _month_start(now: datetime | None = None) -> datetime:
    """The first instant of the current UTC calendar month — what quotas reset on."""
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def count_this_month(db: AsyncSession, *, tenant_id: uuid.UUID, kind: UsageKind) -> int:
    """How many events of `kind` this tenant has recorded since the start of the current month."""
    stmt = (
        select(func.count())
        .select_from(UsageEvent)
        .where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.kind == kind,
            UsageEvent.created_at >= _month_start(),
        )
    )
    return await db.scalar(stmt) or 0


async def sum_cost_this_month(db: AsyncSession, *, tenant_id: uuid.UUID) -> float:
    """Total spend across every kind this tenant has recorded this month — the admin panel's own
    per-tenant spend figure."""
    stmt = select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
        UsageEvent.tenant_id == tenant_id, UsageEvent.created_at >= _month_start()
    )
    return float(await db.scalar(stmt) or 0)
