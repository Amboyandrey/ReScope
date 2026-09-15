"""Creating and listing a company's own scrape job history."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ScrapeJob, ScrapeMode


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
