"""Recording and reading the usage ledger — one row per billable scrape-job step."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageBilledTo, UsageEvent, UsageKind


async def record_usage_event(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID | None,
    kind: UsageKind,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    billed_to: UsageBilledTo = UsageBilledTo.PLATFORM,
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
        billed_to=billed_to,
    )
    db.add(event)
    await db.flush()
    return event


def _month_start(now: datetime | None = None) -> datetime:
    """The first instant of the current UTC calendar month — what quotas reset on."""
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def count_this_month(
    db: AsyncSession, *, tenant_id: uuid.UUID, kind: UsageKind | Sequence[UsageKind]
) -> int:
    """How many events of `kind` (or, given several, any of them — e.g. every kind that counts
    against `deep_runs_per_month`) this tenant has recorded since the start of the current month."""
    # `UsageKind` is a `StrEnum`, which is itself a `Sequence[str]` — `isinstance(kind, UsageKind)`
    # is the only reliable way to tell "one kind" from "several", not `isinstance(kind, Sequence)`.
    kind_filter = UsageEvent.kind == kind if isinstance(kind, UsageKind) else UsageEvent.kind.in_(kind)
    stmt = (
        select(func.count())
        .select_from(UsageEvent)
        .where(
            UsageEvent.tenant_id == tenant_id,
            kind_filter,
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
