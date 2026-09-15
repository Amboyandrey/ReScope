"""A member's own saved search queries — personal, not shared across the tenant."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import SavedSearchNotFound
from app.models import SavedSearch


async def create_saved_search(
    db: AsyncSession, *, tenant_id: uuid.UUID, owner_id: uuid.UUID, name: str, q: str
) -> SavedSearch:
    saved = SavedSearch(tenant_id=tenant_id, owner_id=owner_id, name=name.strip(), query={"q": q})
    db.add(saved)
    await db.flush()
    return saved


async def list_saved_searches(
    db: AsyncSession, *, tenant_id: uuid.UUID, owner_id: uuid.UUID
) -> list[SavedSearch]:
    """Only the caller's own — a saved search is a personal shortcut, not a shared tenant asset."""
    stmt = (
        select(SavedSearch)
        .where(SavedSearch.tenant_id == tenant_id, SavedSearch.owner_id == owner_id)
        .order_by(SavedSearch.created_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def delete_saved_search(
    db: AsyncSession, *, tenant_id: uuid.UUID, owner_id: uuid.UUID, saved_search_id: uuid.UUID
) -> None:
    saved = await db.scalar(
        select(SavedSearch).where(
            SavedSearch.tenant_id == tenant_id,
            SavedSearch.owner_id == owner_id,
            SavedSearch.id == saved_search_id,
        )
    )
    if saved is None:
        raise SavedSearchNotFound()
    await db.delete(saved)
    await db.flush()
