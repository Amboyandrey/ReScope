"""Reading a tenant's audit trail — write-side happens inline in the services that need it."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role
from app.schemas.audit import AuditLogResponse
from app.services.audit import list_audit_logs

router = APIRouter(prefix="/tenants/current/audit-logs", tags=["audit"])

_RequireAdmin = Annotated[TenantCtx, Depends(require_role(Role.ADMIN))]


@router.get("", response_model=list[AuditLogResponse])
async def list_logs(
    db: DbSession, ctx: _RequireAdmin, limit: int = Query(default=50, le=200)
) -> list[AuditLogResponse]:
    """List the current tenant's audit trail, newest first. Admins and owners only."""
    logs = await list_audit_logs(db, tenant_id=ctx.tenant.id, limit=limit)
    return [AuditLogResponse.model_validate(log) for log in logs]
