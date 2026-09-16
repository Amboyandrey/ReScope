"""Filtering a tenant's companies for the catalogue view, and reporting which filter values
actually have at least one company behind them — so the UI never offers an option with zero
results (docs/PLAN.md §11).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CompanyTag, CompanyType, Competency, CompetencyKind, Tag
from app.services.search import semantic_search


@dataclass(frozen=True)
class CatalogueFilters:
    country: str | None = None
    company_type: CompanyType | None = None
    industry: str | None = None
    competency_kind: CompetencyKind | None = None
    tag_id: uuid.UUID | None = None
    q: str | None = None


@dataclass(frozen=True)
class CatalogueFacets:
    countries: list[tuple[str, int]]
    company_types: list[tuple[CompanyType, int]]
    industries: list[tuple[str, int]]
    competency_kinds: list[tuple[CompetencyKind, int]]
    tags: list[tuple[Tag, int]]


def _apply_filters(
    stmt: Select[tuple[Company]], *, tenant_id: uuid.UUID, filters: CatalogueFilters
) -> Select[tuple[Company]]:
    if filters.country:
        stmt = stmt.where(Company.hq_country == filters.country)
    if filters.company_type:
        stmt = stmt.where(Company.company_type == filters.company_type)
    if filters.industry:
        stmt = stmt.where(Company.industry == filters.industry)
    if filters.competency_kind:
        stmt = stmt.where(
            Company.id.in_(
                select(Competency.company_id).where(
                    Competency.tenant_id == tenant_id, Competency.kind == filters.competency_kind
                )
            )
        )
    if filters.tag_id:
        stmt = stmt.where(
            Company.id.in_(
                select(CompanyTag.company_id).where(
                    CompanyTag.tenant_id == tenant_id, CompanyTag.tag_id == filters.tag_id
                )
            )
        )
    return stmt


async def list_catalogue(
    db: AsyncSession, *, tenant_id: uuid.UUID, filters: CatalogueFilters, limit: int = 100
) -> list[Company]:
    """List a tenant's companies matching every given filter. `q` runs semantic search first and
    ranks the result by relevance; every other filter narrows a plain SQL `WHERE`, applied either
    to the semantic candidates or, with no `q`, to the whole tenant ordered newest-first."""
    if filters.q:
        hits = await semantic_search(db, tenant_id=tenant_id, query=filters.q, limit=limit)
        ranked_ids = [hit.company.id for hit in hits]
        if not ranked_ids:
            return []
        stmt = _apply_filters(
            select(Company).where(Company.tenant_id == tenant_id, Company.id.in_(ranked_ids)),
            tenant_id=tenant_id,
            filters=filters,
        )
        by_id = {c.id: c for c in (await db.scalars(stmt)).all()}
        return [by_id[cid] for cid in ranked_ids if cid in by_id]

    stmt = _apply_filters(
        select(Company).where(Company.tenant_id == tenant_id), tenant_id=tenant_id, filters=filters
    )
    stmt = stmt.order_by(Company.created_at.desc()).limit(limit)
    return list((await db.scalars(stmt)).all())


async def get_catalogue_facets(db: AsyncSession, *, tenant_id: uuid.UUID) -> CatalogueFacets:
    """The distinct values (and how many companies match each) behind every catalogue filter."""
    countries = (
        await db.execute(
            select(Company.hq_country, func.count())
            .where(Company.tenant_id == tenant_id, Company.hq_country.is_not(None))
            .group_by(Company.hq_country)
            .order_by(Company.hq_country)
        )
    ).all()
    company_types = (
        await db.execute(
            select(Company.company_type, func.count())
            .where(Company.tenant_id == tenant_id, Company.company_type.is_not(None))
            .group_by(Company.company_type)
            .order_by(Company.company_type)
        )
    ).all()
    industries = (
        await db.execute(
            select(Company.industry, func.count())
            .where(Company.tenant_id == tenant_id, Company.industry.is_not(None))
            .group_by(Company.industry)
            .order_by(Company.industry)
        )
    ).all()
    competency_kinds = (
        await db.execute(
            select(Competency.kind, func.count(func.distinct(Competency.company_id)))
            .where(Competency.tenant_id == tenant_id)
            .group_by(Competency.kind)
            .order_by(Competency.kind)
        )
    ).all()
    tags = (
        await db.execute(
            select(Tag, func.count(CompanyTag.company_id))
            .join(CompanyTag, CompanyTag.tag_id == Tag.id)
            .where(Tag.tenant_id == tenant_id)
            .group_by(Tag.id)
            .order_by(Tag.name)
        )
    ).all()
    return CatalogueFacets(
        countries=[(c, n) for c, n in countries],
        company_types=[(t, n) for t, n in company_types],
        industries=[(i, n) for i, n in industries],
        competency_kinds=[(k, n) for k, n in competency_kinds],
        tags=[(t, n) for t, n in tags],
    )
