"""Diffing a company's profile before and after a re-profile run, and the cron entry point that
finds companies due for one and enqueues a fresh scrape (see docs/PLAN.md §5's "re-profile").
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory, set_tenant_scope
from app.core.errors import QuotaExceeded
from app.models import Company, Competency, Offering, Plan, ProfileStatus, ScrapeMode, Tenant
from app.services.jobs import enqueue_scrape_job
from app.services.platform_settings import get_platform_settings
from app.services.quotas import assert_within_quota
from app.services.scrape_jobs import create_scrape_job

log = structlog.get_logger()


@dataclass
class ProfileSnapshot:
    """What a company's profile said at one point in time — enough to tell what a re-profile
    run changed without needing the full offering/competency rows."""

    overview: str | None
    offerings: frozenset[str] = field(default_factory=frozenset)
    competencies: frozenset[str] = field(default_factory=frozenset)


async def snapshot_profile(db: AsyncSession, *, tenant_id: uuid.UUID, company: Company) -> ProfileSnapshot:
    """Capture a company's current profile, to diff against after its next scrape completes."""
    offerings = await db.scalars(
        select(Offering.name).where(Offering.tenant_id == tenant_id, Offering.company_id == company.id)
    )
    competencies = await db.scalars(
        select(Competency.name).where(Competency.tenant_id == tenant_id, Competency.company_id == company.id)
    )
    return ProfileSnapshot(
        overview=company.overview,
        offerings=frozenset(offerings.all()),
        competencies=frozenset(competencies.all()),
    )


def diff_snapshots(before: ProfileSnapshot, after: ProfileSnapshot) -> dict[str, object] | None:
    """Compare two snapshots of the same company; `None` if nothing worth surfacing changed."""
    diff: dict[str, object] = {}
    if before.overview != after.overview:
        diff["overview"] = {"before": before.overview, "after": after.overview}

    added_offerings = sorted(after.offerings - before.offerings)
    removed_offerings = sorted(before.offerings - after.offerings)
    if added_offerings or removed_offerings:
        diff["offerings"] = {"added": added_offerings, "removed": removed_offerings}

    added_competencies = sorted(after.competencies - before.competencies)
    removed_competencies = sorted(before.competencies - after.competencies)
    if added_competencies or removed_competencies:
        diff["competencies"] = {"added": added_competencies, "removed": removed_competencies}

    return diff or None


async def _due_companies(db: AsyncSession, *, tenant_id: uuid.UUID, interval_days: int) -> list[Company]:
    """A tenant's companies last profiled longer ago than its plan's re-profile interval —
    never a company still mid-scrape or one that has never finished a first profile at all."""
    cutoff = datetime.now(UTC) - timedelta(days=interval_days)
    stmt = select(Company).where(
        Company.tenant_id == tenant_id,
        Company.profile_status == ProfileStatus.DONE,
        Company.last_profiled_at.is_not(None),
        Company.last_profiled_at < cutoff,
    )
    return list((await db.scalars(stmt)).all())


async def enqueue_due_reprofiles() -> int:
    """The scheduler's entry point (see app/workers/main.py's cron job): across every tenant,
    find companies past their plan's re-profile interval and enqueue a fresh scrape for each.
    A tenant already at its monthly quota is skipped rather than failing the whole run — the
    scheduler ticks again next hour and simply tries once more. Returns how many were enqueued.
    """
    enqueued = 0
    async with async_session_factory() as db:
        settings = await get_platform_settings(db)
        if settings.scraping_paused:
            return 0

        tenants = list((await db.scalars(select(Tenant))).all())
        for tenant in tenants:
            await set_tenant_scope(db, tenant.id)
            plan = await db.get(Plan, tenant.plan_id)
            assert plan is not None  # every tenant is created with a valid plan_id
            for company in await _due_companies(
                db, tenant_id=tenant.id, interval_days=plan.reprofile_interval_days
            ):
                try:
                    await assert_within_quota(db, tenant=tenant, mode=ScrapeMode.FAST)
                except QuotaExceeded:
                    break  # this tenant is out of room this month — further companies would be too
                job = await create_scrape_job(
                    db, tenant_id=tenant.id, company_id=company.id, mode=ScrapeMode.FAST
                )
                company.profile_status = ProfileStatus.SCRAPING
                await db.commit()
                await set_tenant_scope(db, tenant.id)  # transaction-local — reset after the commit above
                await enqueue_scrape_job(job_id=job.id, tenant_id=tenant.id, company_id=company.id)
                enqueued += 1
                log.info("reprofile.enqueued", tenant_id=str(tenant.id), company_id=str(company.id))
    return enqueued


__all__ = ["ProfileSnapshot", "diff_snapshots", "enqueue_due_reprofiles", "snapshot_profile"]
