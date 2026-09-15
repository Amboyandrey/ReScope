"""Writing and reading the immutable audit trail — one row per privileged action."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_id: uuid.UUID,
    action: str,
    target_type: str,
    target_id: str,
    ip: str = "internal",
    metadata: dict[str, Any] | None = None,
) -> AuditLog:
    """Append one row to the audit trail. Callers never update or delete it afterward."""
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip=ip,
        event_metadata=metadata,
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_audit_logs(
    db: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 50, before: datetime | None = None
) -> list[AuditLog]:
    """List a tenant's audit trail, newest first, cursor-paginated on `created_at` via `before`."""
    stmt = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if before is not None:
        stmt = stmt.where(AuditLog.created_at < before)
    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())
