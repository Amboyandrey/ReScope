"""CSV import — contacts into one company."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role
from app.schemas.import_job import ImportResponse
from app.services.companies import get_company
from app.services.imports import import_contacts_csv

router = APIRouter(prefix="/tenants/current/companies/{company_id}/contacts", tags=["imports"])

_MemberCtx = Annotated[TenantCtx, Depends(require_role(Role.MEMBER))]
_CsvFile = Annotated[UploadFile, File()]


@router.post("/import", response_model=ImportResponse, status_code=status.HTTP_201_CREATED)
async def import_csv(company_id: uuid.UUID, ctx: _MemberCtx, db: DbSession, file: _CsvFile) -> ImportResponse:
    """Upload a CSV of contacts for this company. Columns are matched by common header names
    (first_name/last_name required; email, title, phone, linkedin_url optional) — a row missing a
    name is skipped and recorded, not fatal to the rest of the file.
    """
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    data = await file.read()
    record = await import_contacts_csv(
        db, tenant_id=ctx.tenant.id, company_id=company_id, created_by=ctx.user.id, csv_bytes=data
    )
    return ImportResponse.model_validate(record)
