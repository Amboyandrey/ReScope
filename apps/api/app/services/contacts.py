"""Adding, listing, updating, and removing a company's contacts."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Contact


class ContactNotFound(AppError):
    status_code = 404
    detail = "Contact not found."


async def create_contact(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    first_name: str,
    last_name: str,
    email: str | None = None,
    title: str | None = None,
    phone: str | None = None,
    linkedin_url: str | None = None,
    source: str = "manual",
) -> Contact:
    contact = Contact(
        tenant_id=tenant_id,
        company_id=company_id,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=email,
        title=title,
        phone=phone,
        linkedin_url=linkedin_url,
        source=source,
    )
    db.add(contact)
    await db.flush()
    return contact


async def list_contacts(db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> list[Contact]:
    stmt = (
        select(Contact)
        .where(Contact.tenant_id == tenant_id, Contact.company_id == company_id)
        .order_by(Contact.created_at)
    )
    return list((await db.scalars(stmt)).all())


async def get_contact(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, contact_id: uuid.UUID
) -> Contact:
    contact = await db.scalar(
        select(Contact).where(
            Contact.tenant_id == tenant_id, Contact.company_id == company_id, Contact.id == contact_id
        )
    )
    if contact is None:
        raise ContactNotFound()
    return contact


async def update_contact(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, contact_id: uuid.UUID, **fields: object
) -> Contact:
    contact = await get_contact(db, tenant_id=tenant_id, company_id=company_id, contact_id=contact_id)
    for key, value in fields.items():
        if value is not None:
            setattr(contact, key, value)
    await db.flush()
    # updated_at's onupdate=func.now() is a server-side default: after flush() it's expired, not
    # populated, and reading an expired attribute needs an implicit lazy-load that Pydantic's own
    # synchronous model_validate can't provide (raises MissingGreenlet) — refresh() reads it back
    # explicitly while still in an async context. Same fix as platform_settings.py's own.
    await db.refresh(contact)
    return contact


async def delete_contact(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, contact_id: uuid.UUID
) -> None:
    contact = await get_contact(db, tenant_id=tenant_id, company_id=company_id, contact_id=contact_id)
    await db.delete(contact)
    await db.flush()
