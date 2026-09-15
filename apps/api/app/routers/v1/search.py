"""Semantic search over a tenant's companies, and finding companies similar to one another."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role
from app.schemas.company import CompanyResponse, SearchHitResponse, SimilarCompanyResponse
from app.services.companies import get_company
from app.services.search import semantic_search, similar_companies

router = APIRouter(prefix="/tenants/current", tags=["search"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]


@router.get("/search", response_model=list[SearchHitResponse])
async def search(
    ctx: _ViewerCtx, db: DbSession, q: str = Query(min_length=1, max_length=500)
) -> list[SearchHitResponse]:
    """Semantic search across every offering, competency, and company summary in this tenant."""
    hits = await semantic_search(db, tenant_id=ctx.tenant.id, query=q)
    return [
        SearchHitResponse(
            company=CompanyResponse.model_validate(hit.company),
            source_kind=hit.source_kind.value,
            content=hit.content,
            distance=hit.distance,
        )
        for hit in hits
    ]


@router.get("/companies/{company_id}/similar", response_model=list[SimilarCompanyResponse])
async def similar(company_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> list[SimilarCompanyResponse]:
    """Companies in this tenant whose profile reads closest to this one's."""
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    results = await similar_companies(db, tenant_id=ctx.tenant.id, company_id=company_id)
    return [
        SimilarCompanyResponse(company=CompanyResponse.model_validate(c), distance=dist)
        for c, dist in results
    ]
