"""Listing, promoting/demoting, and removing tenant members — with the last-owner invariant."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import InsufficientRole, LastOwnerError, MemberNotFound
from app.models import Membership, Role, User


async def list_members(db: AsyncSession, *, tenant_id: uuid.UUID) -> list[tuple[Membership, User]]:
    """List every member of a tenant with their user record, in the order they joined."""
    stmt = (
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant_id)
        .order_by(Membership.created_at)
    )
    return [(member, user) for member, user in (await db.execute(stmt)).all()]


async def _owner_count(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Count how many owners a tenant currently has."""
    stmt = (
        select(func.count())
        .select_from(Membership)
        .where(Membership.tenant_id == tenant_id, Membership.role == Role.OWNER)
    )
    return await db.scalar(stmt) or 0


async def _get_member(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    """Load a membership row by its composite key, or raise if the target isn't a member."""
    member = await db.get(Membership, {"tenant_id": tenant_id, "user_id": user_id})
    if member is None:
        raise MemberNotFound()
    return member


async def change_member_role(
    db: AsyncSession, *, tenant_id: uuid.UUID, acting_role: Role, target_user_id: uuid.UUID, new_role: Role
) -> Membership:
    """Change a member's role — only an owner may touch the owner role, and one must always remain."""
    member = await _get_member(db, tenant_id, target_user_id)
    if (member.role == Role.OWNER or new_role == Role.OWNER) and acting_role != Role.OWNER:
        raise InsufficientRole()
    if member.role == Role.OWNER and new_role != Role.OWNER and await _owner_count(db, tenant_id) <= 1:
        raise LastOwnerError()
    member.role = new_role
    await db.flush()
    return member


async def remove_member(
    db: AsyncSession, *, tenant_id: uuid.UUID, acting_role: Role, target_user_id: uuid.UUID
) -> None:
    """Remove a member — only an owner may remove another owner, and one must always remain."""
    member = await _get_member(db, tenant_id, target_user_id)
    if member.role == Role.OWNER and acting_role != Role.OWNER:
        raise InsufficientRole()
    if member.role == Role.OWNER and await _owner_count(db, tenant_id) <= 1:
        raise LastOwnerError()
    await db.delete(member)
    await db.flush()
