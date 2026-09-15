"""List, promote/demote, and remove tenant members."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role, User
from app.schemas.member import RoleUpdate
from app.schemas.tenant import MemberResponse
from app.services.audit import record_audit
from app.services.members import change_member_role, list_members, remove_member

router = APIRouter(prefix="/tenants/current/members", tags=["members"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]
_AdminCtx = Annotated[TenantCtx, Depends(require_role(Role.ADMIN))]


@router.get("", response_model=list[MemberResponse])
async def list_members_route(ctx: _ViewerCtx, db: DbSession) -> list[MemberResponse]:
    """List every member of the current tenant, in the order they joined."""
    rows = await list_members(db, tenant_id=ctx.tenant.id)
    return [
        MemberResponse(
            user_id=u.id, email=u.email, display_name=u.display_name, role=m.role, joined_at=m.created_at
        )
        for m, u in rows
    ]


@router.patch("/{user_id}", response_model=MemberResponse)
async def change_role_route(
    user_id: uuid.UUID, body: RoleUpdate, ctx: _AdminCtx, db: DbSession
) -> MemberResponse:
    """Change a member's role."""
    member = await change_member_role(
        db, tenant_id=ctx.tenant.id, acting_role=ctx.role, target_user_id=user_id, new_role=body.role
    )
    user = await db.get(User, user_id)
    assert user is not None  # change_member_role already confirmed this membership exists
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="member.role_changed",
        target_type="user",
        target_id=str(user_id),
        metadata={"new_role": member.role.value},
    )
    return MemberResponse(
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=member.role,
        joined_at=member.created_at,
    )


@router.delete("/{user_id}", status_code=204)
async def remove_member_route(user_id: uuid.UUID, ctx: _AdminCtx, db: DbSession) -> None:
    """Remove a member from the current tenant."""
    await remove_member(db, tenant_id=ctx.tenant.id, acting_role=ctx.role, target_user_id=user_id)
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="member.removed",
        target_type="user",
        target_id=str(user_id),
    )
