"""Creating and listing a tenant's tags, and attaching/detaching them to companies."""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import TagAlreadyExists, TagNotFound
from app.models import CompanyTag, Tag


async def create_tag(db: AsyncSession, *, tenant_id: uuid.UUID, name: str, color: str) -> Tag:
    tag = Tag(tenant_id=tenant_id, name=name.strip(), color=color)
    db.add(tag)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise TagAlreadyExists() from exc
    return tag


async def list_tags(db: AsyncSession, *, tenant_id: uuid.UUID) -> list[Tag]:
    stmt = select(Tag).where(Tag.tenant_id == tenant_id).order_by(Tag.name)
    return list((await db.scalars(stmt)).all())


async def delete_tag(db: AsyncSession, *, tenant_id: uuid.UUID, tag_id: uuid.UUID) -> None:
    tag = await db.scalar(select(Tag).where(Tag.tenant_id == tenant_id, Tag.id == tag_id))
    if tag is None:
        raise TagNotFound()
    await db.delete(tag)
    await db.flush()


async def list_company_tags(db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> list[Tag]:
    stmt = (
        select(Tag)
        .join(CompanyTag, CompanyTag.tag_id == Tag.id)
        .where(CompanyTag.tenant_id == tenant_id, CompanyTag.company_id == company_id)
        .order_by(Tag.name)
    )
    return list((await db.scalars(stmt)).all())


async def attach_tag(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, tag_id: uuid.UUID
) -> None:
    """Attach a tag to a company. Idempotent — attaching an already-attached tag is a no-op, not
    a conflict, so a UI doesn't need to check membership before offering the action."""
    tag = await db.scalar(select(Tag).where(Tag.tenant_id == tenant_id, Tag.id == tag_id))
    if tag is None:
        raise TagNotFound()
    stmt = (
        pg_insert(CompanyTag)
        .values(tenant_id=tenant_id, company_id=company_id, tag_id=tag_id)
        .on_conflict_do_nothing()
    )
    await db.execute(stmt)
    await db.flush()


async def detach_tag(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, tag_id: uuid.UUID
) -> None:
    """Detach a tag from a company. Also idempotent — detaching a tag that was never attached
    (or already removed) succeeds silently rather than 404ing."""
    row = await db.scalar(
        select(CompanyTag).where(
            CompanyTag.tenant_id == tenant_id,
            CompanyTag.company_id == company_id,
            CompanyTag.tag_id == tag_id,
        )
    )
    if row is not None:
        await db.delete(row)
        await db.flush()
