"""The arq job that actually runs one company's scrape — Chromium, so it only ever runs in the
dedicated `scraper` worker process/image (infra/Dockerfile.scraper), never the lightweight one.

Opens its own database session and (re-)sets row-level-security scope before every commit — that
scope is transaction-local, the same discipline ReCore's own connector-indexing job follows (see
app/workers/index_connector.py there). Any failure anywhere in the pipeline lands the job and its
company in FAILED with the error recorded, never as an unhandled exception that just looks like
the job silently vanishing.
"""

import uuid
from typing import Any

from app.core.db import async_session_factory, set_tenant_scope
from app.models import Company, ProfileStatus, ScrapeJob, ScrapeStatus
from app.scraping.pipeline import run_scrape_job


async def scrape_company(ctx: dict[str, Any], job_id: str, tenant_id: str, company_id: str) -> None:
    """Run one scrape job end to end. `ctx` is arq's own per-job context, unused here."""
    del ctx
    jid, tid, cid = uuid.UUID(job_id), uuid.UUID(tenant_id), uuid.UUID(company_id)

    async with async_session_factory() as db:
        await set_tenant_scope(db, tid)
        job = await db.get(ScrapeJob, jid)
        company = await db.get(Company, cid)
        if job is None or company is None:
            return  # deleted before the job ran — nothing to do

        try:
            await run_scrape_job(db, job=job, company=company)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — recorded on the job, never left unhandled
            await db.rollback()
            await set_tenant_scope(db, tid)  # transaction-local — reset after the rollback above
            job = await db.get(ScrapeJob, jid)
            company = await db.get(Company, cid)
            if job is not None:
                job.status = ScrapeStatus.FAILED
                job.error = str(exc)[:2000]
            if company is not None:
                company.profile_status = ProfileStatus.FAILED
            await db.commit()
