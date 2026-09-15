"""Adding a company to a tenant's list, and reading back what's known about it so far."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.errors import InsufficientRole
from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role
from app.schemas.company import (
    CompanyDetailResponse,
    CompanyResponse,
    CompetencyResponse,
    CreateCompanyRequest,
    OfferingResponse,
)
from app.services.audit import record_audit
from app.services.companies import (
    create_company,
    delete_company,
    get_company,
    get_competencies,
    get_offerings,
    list_companies,
)

router = APIRouter(prefix="/tenants/current/companies", tags=["companies"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]
_MemberCtx = Annotated[TenantCtx, Depends(require_role(Role.MEMBER))]


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create(body: CreateCompanyRequest, ctx: _MemberCtx, db: DbSession) -> CompanyResponse:
    """Add a company to the current tenant by its domain or website URL."""
    company = await create_company(db, tenant_id=ctx.tenant.id, created_by=ctx.user, raw_domain=body.domain)
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="company.created",
        target_type="company",
        target_id=str(company.id),
        metadata={"domain": company.domain},
    )
    return CompanyResponse.model_validate(company)


@router.get("", response_model=list[CompanyResponse])
async def list_all(ctx: _ViewerCtx, db: DbSession) -> list[CompanyResponse]:
    """List every company tracked in the current tenant."""
    companies = await list_companies(db, tenant_id=ctx.tenant.id)
    return [CompanyResponse.model_validate(c) for c in companies]


@router.get("/{company_id}", response_model=CompanyDetailResponse)
async def get_one(company_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> CompanyDetailResponse:
    """Fetch one company along with every offering and competency extracted for it so far."""
    company = await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)
    offerings = await get_offerings(db, tenant_id=ctx.tenant.id, company_id=company_id)
    competencies = await get_competencies(db, tenant_id=ctx.tenant.id, company_id=company_id)
    return CompanyDetailResponse(
        **CompanyResponse.model_validate(company).model_dump(),
        offerings=[OfferingResponse.model_validate(o) for o in offerings],
        competencies=[CompetencyResponse.model_validate(c) for c in competencies],
    )


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(company_id: uuid.UUID, ctx: _MemberCtx, db: DbSession) -> None:
    """Remove a company from the current tenant. Admin/owner only if it isn't the caller's own add."""
    company = await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)
    if company.created_by != ctx.user.id and not _is_at_least_admin(ctx.role):
        raise InsufficientRole()
    await delete_company(db, tenant_id=ctx.tenant.id, company_id=company_id)
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="company.deleted",
        target_type="company",
        target_id=str(company_id),
    )


def _is_at_least_admin(role: Role) -> bool:
    return role in (Role.ADMIN, Role.OWNER)
