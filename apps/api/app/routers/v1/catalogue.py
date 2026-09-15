"""Browsing and filtering a tenant's companies by fact, competency kind, and tag."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import CompanyType, CompetencyKind, Role
from app.schemas.catalogue import (
    CatalogueFacetsResponse,
    CompanyTypeFacet,
    CompetencyKindFacet,
    FacetValue,
    TagFacet,
)
from app.schemas.company import CompanyDetailResponse, CompanyResponse, CompetencyResponse, OfferingResponse
from app.services.catalogue import CatalogueFilters, get_catalogue_facets, list_catalogue
from app.services.companies import get_competencies, get_offerings

router = APIRouter(prefix="/tenants/current/catalogue", tags=["catalogue"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]
_Country = Annotated[str | None, Query(max_length=2)]
_CompanyTypeFilter = Annotated[CompanyType | None, Query()]
_Industry = Annotated[str | None, Query(max_length=120)]
_CompetencyKindFilter = Annotated[CompetencyKind | None, Query()]
_TagFilter = Annotated[uuid.UUID | None, Query()]
_SearchQuery = Annotated[str | None, Query(min_length=1, max_length=500)]


@router.get("", response_model=list[CompanyDetailResponse])
async def list_catalogue_route(
    ctx: _ViewerCtx,
    db: DbSession,
    country: _Country = None,
    company_type: _CompanyTypeFilter = None,
    industry: _Industry = None,
    competency_kind: _CompetencyKindFilter = None,
    tag: _TagFilter = None,
    q: _SearchQuery = None,
) -> list[CompanyDetailResponse]:
    """List this tenant's companies, each with its offerings and competencies, narrowed by
    whichever filters are given. `q` ranks by semantic relevance; combined with other filters, it
    searches within what those filters already narrowed down to."""
    filters = CatalogueFilters(
        country=country.upper() if country else None,
        company_type=company_type,
        industry=industry,
        competency_kind=competency_kind,
        tag_id=tag,
        q=q,
    )
    companies = await list_catalogue(db, tenant_id=ctx.tenant.id, filters=filters)
    results = []
    for company in companies:
        offerings = await get_offerings(db, tenant_id=ctx.tenant.id, company_id=company.id)
        competencies = await get_competencies(db, tenant_id=ctx.tenant.id, company_id=company.id)
        results.append(
            CompanyDetailResponse(
                **CompanyResponse.model_validate(company).model_dump(),
                offerings=[OfferingResponse.model_validate(o) for o in offerings],
                competencies=[CompetencyResponse.model_validate(c) for c in competencies],
            )
        )
    return results


@router.get("/facets", response_model=CatalogueFacetsResponse)
async def get_facets(ctx: _ViewerCtx, db: DbSession) -> CatalogueFacetsResponse:
    """The values behind every catalogue filter that at least one company actually has."""
    facets = await get_catalogue_facets(db, tenant_id=ctx.tenant.id)
    return CatalogueFacetsResponse(
        countries=[FacetValue(value=v, count=n) for v, n in facets.countries],
        company_types=[CompanyTypeFacet(value=v, count=n) for v, n in facets.company_types],
        industries=[FacetValue(value=v, count=n) for v, n in facets.industries],
        competency_kinds=[CompetencyKindFacet(value=v, count=n) for v, n in facets.competency_kinds],
        tags=[TagFacet(id=t.id, name=t.name, color=t.color, count=n) for t, n in facets.tags],
    )
