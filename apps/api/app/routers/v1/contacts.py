"""A company's contacts — the people a member tracks there."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role
from app.schemas.contact import ContactResponse, CreateContactRequest, UpdateContactRequest
from app.services.companies import get_company
from app.services.contacts import create_contact, delete_contact, list_contacts, update_contact

router = APIRouter(prefix="/tenants/current/companies/{company_id}/contacts", tags=["contacts"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]
_MemberCtx = Annotated[TenantCtx, Depends(require_role(Role.MEMBER))]


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create(
    company_id: uuid.UUID, body: CreateContactRequest, ctx: _MemberCtx, db: DbSession
) -> ContactResponse:
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    contact = await create_contact(
        db,
        tenant_id=ctx.tenant.id,
        company_id=company_id,
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        title=body.title,
        phone=body.phone,
        linkedin_url=body.linkedin_url,
    )
    return ContactResponse.model_validate(contact)


@router.get("", response_model=list[ContactResponse])
async def list_all(company_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> list[ContactResponse]:
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)
    contacts = await list_contacts(db, tenant_id=ctx.tenant.id, company_id=company_id)
    return [ContactResponse.model_validate(c) for c in contacts]


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update(
    company_id: uuid.UUID,
    contact_id: uuid.UUID,
    body: UpdateContactRequest,
    ctx: _MemberCtx,
    db: DbSession,
) -> ContactResponse:
    contact = await update_contact(
        db,
        tenant_id=ctx.tenant.id,
        company_id=company_id,
        contact_id=contact_id,
        **body.model_dump(exclude_unset=True),
    )
    return ContactResponse.model_validate(contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(company_id: uuid.UUID, contact_id: uuid.UUID, ctx: _MemberCtx, db: DbSession) -> None:
    await delete_contact(db, tenant_id=ctx.tenant.id, company_id=company_id, contact_id=contact_id)
