"""A company's notes — free text a member leaves for the rest of the tenant to see."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role
from app.schemas.note import CreateNoteRequest, NoteResponse
from app.services.companies import get_company
from app.services.notes import create_note, delete_note, list_notes

router = APIRouter(prefix="/tenants/current/companies/{company_id}/notes", tags=["notes"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]
_MemberCtx = Annotated[TenantCtx, Depends(require_role(Role.MEMBER))]


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create(
    company_id: uuid.UUID, body: CreateNoteRequest, ctx: _MemberCtx, db: DbSession
) -> NoteResponse:
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    note = await create_note(
        db, tenant_id=ctx.tenant.id, company_id=company_id, author_id=ctx.user.id, body=body.body
    )
    return NoteResponse.model_validate(note)


@router.get("", response_model=list[NoteResponse])
async def list_all(company_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> list[NoteResponse]:
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)
    notes = await list_notes(db, tenant_id=ctx.tenant.id, company_id=company_id)
    return [NoteResponse.model_validate(n) for n in notes]


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(company_id: uuid.UUID, note_id: uuid.UUID, ctx: _MemberCtx, db: DbSession) -> None:
    await delete_note(db, tenant_id=ctx.tenant.id, company_id=company_id, note_id=note_id)
