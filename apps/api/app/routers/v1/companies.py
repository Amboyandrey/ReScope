"""Adding a company to a tenant's list, and reading back what's known about it so far."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.errors import InsufficientRole
from app.core.storage import read_screenshot
from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import ProfileStatus, Role
from app.schemas.company import (
    CompanyDetailResponse,
    CompanyResponse,
    CompetencyResponse,
    CreateCompanyRequest,
    OfferingResponse,
    ScrapeJobResponse,
    ScrapePageResponse,
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
from app.services.jobs import enqueue_scrape_job
from app.services.platform_settings import assert_scraping_not_paused
from app.services.quotas import assert_within_quota
from app.services.scrape_jobs import (
    ScrapePageNotFound,
    create_scrape_job,
    get_scrape_page,
    list_scrape_jobs,
    list_scrape_pages,
)

router = APIRouter(prefix="/tenants/current/companies", tags=["companies"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]
_MemberCtx = Annotated[TenantCtx, Depends(require_role(Role.MEMBER))]


@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create(body: CreateCompanyRequest, ctx: _MemberCtx, db: DbSession) -> CompanyResponse:
    """Add a company to the current tenant and queue its first scrape.

    Quota and the killswitch are both checked before anything is written — a rejected request
    leaves no orphaned company or job row behind, and a tenant's plan is never charged for a run
    that never happened.
    """
    await assert_scraping_not_paused(db)
    await assert_within_quota(db, tenant=ctx.tenant, mode=body.mode)
    company = await create_company(db, tenant_id=ctx.tenant.id, created_by=ctx.user, raw_domain=body.domain)
    job = await create_scrape_job(db, tenant_id=ctx.tenant.id, company_id=company.id, mode=body.mode)
    company.profile_status = ProfileStatus.SCRAPING
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="company.created",
        target_type="company",
        target_id=str(company.id),
        metadata={"domain": company.domain},
    )
    # Enqueued here, ahead of this request's own commit (which get_db() runs once this handler
    # returns) — the same ordering ReCore's own connector-indexing trigger uses. In the rare case
    # the worker dequeues and looks the job up before that commit lands, it finds nothing and
    # returns without error; Redis enqueue plus worker pickup latency make that window small
    # enough in practice not to need more than this note.
    await enqueue_scrape_job(job_id=job.id, tenant_id=ctx.tenant.id, company_id=company.id)
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


@router.get("/{company_id}/scrape-jobs", response_model=list[ScrapeJobResponse])
async def list_jobs(company_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> list[ScrapeJobResponse]:
    """List a company's scrape jobs, most recent first — what a job-status UI polls."""
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    jobs = await list_scrape_jobs(db, tenant_id=ctx.tenant.id, company_id=company_id)
    return [ScrapeJobResponse.model_validate(j) for j in jobs]


@router.get("/{company_id}/scrape-jobs/{job_id}/pages", response_model=list[ScrapePageResponse])
async def list_pages(
    company_id: uuid.UUID, job_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession
) -> list[ScrapePageResponse]:
    """List the pages one scrape job read — the raw evidence behind its extraction, including
    which of them Tier 2 also screenshotted."""
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    pages = await list_scrape_pages(db, tenant_id=ctx.tenant.id, job_id=job_id)
    return [
        ScrapePageResponse(
            id=p.id,
            url=p.url,
            status_code=p.status_code,
            has_screenshot=p.screenshot_key is not None,
            fetched_at=p.fetched_at,
        )
        for p in pages
    ]


@router.get("/{company_id}/scrape-jobs/{job_id}/pages/{page_id}/screenshot")
async def get_screenshot(
    company_id: uuid.UUID, job_id: uuid.UUID, page_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession
) -> Response:
    """Stream back one page's Tier 2 screenshot — the actual evidence behind a visually-explored
    fact, not just its markdown transcript."""
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    page = await get_scrape_page(db, tenant_id=ctx.tenant.id, job_id=job_id, page_id=page_id)
    if page.screenshot_key is None:
        raise ScrapePageNotFound("This page has no screenshot.")
    return Response(content=read_screenshot(page.screenshot_key), media_type="image/png")


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
