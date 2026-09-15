"""Adding, listing, and removing a company's notes. No editing — a note is written once."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Note


class NoteNotFound(AppError):
    status_code = 404
    detail = "Note not found."


async def create_note(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, author_id: uuid.UUID, body: str
) -> Note:
    note = Note(tenant_id=tenant_id, company_id=company_id, author_id=author_id, body=body.strip())
    db.add(note)
    await db.flush()
    return note


async def list_notes(db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> list[Note]:
    stmt = (
        select(Note)
        .where(Note.tenant_id == tenant_id, Note.company_id == company_id)
        .order_by(Note.created_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def delete_note(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, note_id: uuid.UUID
) -> None:
    note = await db.scalar(
        select(Note).where(Note.tenant_id == tenant_id, Note.company_id == company_id, Note.id == note_id)
    )
    if note is None:
        raise NoteNotFound()
    await db.delete(note)
    await db.flush()
