"""Creating and listing a company's own scrape job history."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import ScrapeJob, ScrapeMode, ScrapePage


class ScrapePageNotFound(AppError):
    status_code = 404
    detail = "Scrape page not found."


async def create_scrape_job(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, mode: ScrapeMode = ScrapeMode.FAST
) -> ScrapeJob:
    """Record a new queued job. The caller enqueues it onto the worker separately — see
    services/jobs.py — once this row (and the company it points at) are safely committed."""
    job = ScrapeJob(tenant_id=tenant_id, company_id=company_id, mode=mode)
    db.add(job)
    await db.flush()
    return job


async def list_scrape_jobs(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> list[ScrapeJob]:
    """List a company's scrape jobs, most recent first — what a job-status UI polls."""
    stmt = (
        select(ScrapeJob)
        .where(ScrapeJob.tenant_id == tenant_id, ScrapeJob.company_id == company_id)
        .order_by(ScrapeJob.queued_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def list_scrape_pages(db: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> list[ScrapePage]:
    """List the pages one scrape job read, oldest first — the raw evidence behind its extraction."""
    stmt = (
        select(ScrapePage)
        .where(ScrapePage.tenant_id == tenant_id, ScrapePage.job_id == job_id)
        .order_by(ScrapePage.fetched_at)
    )
    return list((await db.scalars(stmt)).all())


async def get_scrape_page(
    db: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID, page_id: uuid.UUID
) -> ScrapePage:
    page = await db.scalar(
        select(ScrapePage).where(
            ScrapePage.tenant_id == tenant_id, ScrapePage.job_id == job_id, ScrapePage.id == page_id
        )
    )
    if page is None:
        raise ScrapePageNotFound()
    return page
