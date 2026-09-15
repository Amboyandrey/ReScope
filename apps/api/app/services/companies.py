"""Adding a company to a tenant's list, and reading it (and its extracted profile) back."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.domains import normalize_domain
from app.core.errors import CompanyAlreadyTracked, CompanyNotFound
from app.core.ssrf import UnsafeUrlError, assert_safe_url
from app.models import Company, Competency, Offering, User


async def create_company(
    db: AsyncSession, *, tenant_id: uuid.UUID, created_by: User, raw_domain: str
) -> Company:
    """Add a company by its domain or website URL. Its profile starts empty — a caller enqueues
    the actual scrape job once this returns."""
    domain, website_url = normalize_domain(raw_domain)
    try:
        assert_safe_url(website_url)
    except UnsafeUrlError as exc:
        raise UnsafeUrlError(f"{domain} does not resolve to a public address.") from exc

    company = Company(
        tenant_id=tenant_id, domain=domain, name=domain, website_url=website_url, created_by=created_by.id
    )
    db.add(company)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise CompanyAlreadyTracked() from exc
    return company


async def list_companies(db: AsyncSession, *, tenant_id: uuid.UUID) -> list[Company]:
    """List every company tracked in a tenant, most recently added first."""
    stmt = select(Company).where(Company.tenant_id == tenant_id).order_by(Company.created_at.desc())
    return list((await db.scalars(stmt)).all())


async def get_company(db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> Company:
    """Fetch one company, or 404 — RLS backstops the tenant filter, this is the app-level check."""
    company = await db.scalar(select(Company).where(Company.tenant_id == tenant_id, Company.id == company_id))
    if company is None:
        raise CompanyNotFound()
    return company


async def get_offerings(db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> list[Offering]:
    stmt = (
        select(Offering)
        .where(Offering.tenant_id == tenant_id, Offering.company_id == company_id)
        .order_by(Offering.created_at)
    )
    return list((await db.scalars(stmt)).all())


async def get_competencies(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> list[Competency]:
    stmt = (
        select(Competency)
        .where(Competency.tenant_id == tenant_id, Competency.company_id == company_id)
        .order_by(Competency.created_at)
    )
    return list((await db.scalars(stmt)).all())


async def delete_company(db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
    company = await get_company(db, tenant_id=tenant_id, company_id=company_id)
    await db.delete(company)
    await db.flush()
