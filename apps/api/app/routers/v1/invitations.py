"""Creating and listing invites (tenant-scoped), and redeeming one by its token (not scoped —
the token itself, not tenant membership, is what authorizes reading and accepting an invite).

Also the by-id "pending for me" flow: a signed-in account whose email has an outstanding invite,
even one it never followed the original link for, can list and accept those without a token.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.core.db import set_tenant_scope
from app.core.errors import RateLimited
from app.deps.auth import CurrentUser, RedisClient
from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Invitation, Role, Tenant
from app.schemas.member import InviteCreate, InviteOut, InvitePreview, PendingInvitationOut
from app.schemas.tenant import MyTenantResponse, TenantResponse
from app.services.audit import record_audit
from app.services.invitations import (
    accept_invitation,
    create_invitation,
    get_invitation_by_token,
    get_pending_invitation_by_id,
    list_pending_invitations,
    list_pending_invitations_for_email,
    revoke_invitation,
)
from app.services.rate_limit import check_rate_limit

settings = get_settings()

tenant_router = APIRouter(prefix="/tenants/current/invitations", tags=["invitations"])
token_router = APIRouter(prefix="/invitations", tags=["invitations"])

_AdminCtx = Annotated[TenantCtx, Depends(require_role(Role.ADMIN))]


@tenant_router.post("", status_code=201, response_model=InviteOut)
async def create_invitation_route(
    body: InviteCreate, ctx: _AdminCtx, db: DbSession, redis: RedisClient
) -> InviteOut:
    """Invite someone into the current tenant. The token is only ever shown in this response."""
    allowed = await check_rate_limit(
        redis,
        f"rl:invite:{ctx.tenant.id}",
        limit=settings.auth_rate_limit_max,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimited()
    invitation, token = await create_invitation(
        db,
        tenant_id=ctx.tenant.id,
        invited_by=ctx.user,
        acting_role=ctx.role,
        email=body.email,
        role=body.role,
    )
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="invitation.created",
        target_type="invitation",
        target_id=str(invitation.id),
        metadata={"email": invitation.email, "role": invitation.role.value},
    )
    return InviteOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
        token=token,
    )


@tenant_router.get("", response_model=list[InviteOut])
async def list_invitations_route(ctx: _AdminCtx, db: DbSession) -> list[InviteOut]:
    """List invitations for the current tenant that haven't been accepted yet."""
    invitations = await list_pending_invitations(db, tenant_id=ctx.tenant.id)
    return [InviteOut(id=i.id, email=i.email, role=i.role, expires_at=i.expires_at) for i in invitations]


@tenant_router.delete("/{invitation_id}", status_code=204)
async def revoke_invitation_route(invitation_id: uuid.UUID, ctx: _AdminCtx, db: DbSession) -> None:
    """Withdraw a pending invitation — its link stops working immediately."""
    await revoke_invitation(db, tenant_id=ctx.tenant.id, invitation_id=invitation_id)
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="invitation.revoked",
        target_type="invitation",
        target_id=str(invitation_id),
    )


# Declared before `/{token}` below: both are a bare GET one segment under /invitations, and
# Starlette matches path templates in registration order — this literal route must come first or
# a request for "pending" would be swallowed by the token route with token="pending".
@token_router.get("/pending", response_model=list[PendingInvitationOut])
async def list_my_pending_invitations_route(user: CurrentUser, db: DbSession) -> list[PendingInvitationOut]:
    """List every outstanding invite waiting for the signed-in account's email."""
    invitations = await list_pending_invitations_for_email(db, email=user.email)
    out = []
    for invitation in invitations:
        tenant = await db.get(Tenant, invitation.tenant_id)
        assert tenant is not None
        out.append(
            PendingInvitationOut(
                id=invitation.id,
                tenant_name=tenant.name,
                role=invitation.role,
                expires_at=invitation.expires_at,
            )
        )
    return out


async def _accept_and_respond(db: DbSession, user: CurrentUser, invitation: Invitation) -> MyTenantResponse:
    """Shared tail of both accept routes: turn the invitation into a membership and audit it.

    Neither accept route runs through `get_tenant_ctx` — the caller isn't a member yet, which is
    the whole point of this flow — so `app.tenant_id` was never set on this connection. The
    invitation already names its tenant, so this sets the scope explicitly before writing the
    audit row: without it, the `INSERT ... RETURNING` audit_logs itself requires would fail its
    own SELECT policy, the same RETURNING-vs-SELECT-policy interaction ReCore's RLS migration
    documents for its `audit_logs` exclusion — here it's solved by setting scope, not excluding.
    """
    member = await accept_invitation(db, invitation=invitation, user=user)
    tenant = await db.get(Tenant, invitation.tenant_id)
    assert tenant is not None
    await set_tenant_scope(db, tenant.id)
    await record_audit(
        db,
        tenant_id=tenant.id,
        actor_id=user.id,
        action="invitation.accepted",
        target_type="invitation",
        target_id=str(invitation.id),
        metadata={"role": member.role.value},
    )
    return MyTenantResponse(**TenantResponse.model_validate(tenant).model_dump(), role=member.role)


@token_router.post("/pending/{invitation_id}/accept", response_model=MyTenantResponse)
async def accept_pending_invitation_route(
    invitation_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> MyTenantResponse:
    """Accept an invite by id, no token needed — the account's email must still match the invite."""
    invitation = await get_pending_invitation_by_id(db, invitation_id=invitation_id)
    return await _accept_and_respond(db, user, invitation)


@token_router.get("/{token}", response_model=InvitePreview)
async def preview_invitation_route(token: str, db: DbSession) -> InvitePreview:
    """Preview an invitation before signing in — reachable without an account."""
    invitation = await get_invitation_by_token(db, token)
    tenant = await db.get(Tenant, invitation.tenant_id)
    assert tenant is not None  # a tenant is never deleted while it still has invitations
    return InvitePreview(
        tenant_name=tenant.name,
        email=invitation.email,
        role=invitation.role,
        expires_at=invitation.expires_at,
    )


@token_router.post("/{token}/accept", response_model=MyTenantResponse)
async def accept_invitation_route(token: str, user: CurrentUser, db: DbSession) -> MyTenantResponse:
    """Accept an invitation — the signed-in account's email must match the one invited."""
    invitation = await get_invitation_by_token(db, token)
    return await _accept_and_respond(db, user, invitation)
