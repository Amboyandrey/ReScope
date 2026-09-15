"""A member's own saved search queries."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role, SavedSearch
from app.schemas.saved_search import CreateSavedSearchRequest, SavedSearchResponse
from app.services.saved_searches import create_saved_search, delete_saved_search, list_saved_searches

router = APIRouter(prefix="/tenants/current/saved-searches", tags=["saved-searches"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]


def _to_response(saved: SavedSearch) -> SavedSearchResponse:
    # query is stored as {"q": "..."} — pulled flat here since SavedSearchResponse.q is its own
    # top-level field, not a nested object model_validate(from_attributes=True) could produce.
    return SavedSearchResponse(id=saved.id, name=saved.name, q=saved.query["q"], created_at=saved.created_at)


@router.post("", response_model=SavedSearchResponse, status_code=status.HTTP_201_CREATED)
async def create(body: CreateSavedSearchRequest, ctx: _ViewerCtx, db: DbSession) -> SavedSearchResponse:
    saved = await create_saved_search(
        db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id, name=body.name, q=body.q
    )
    return _to_response(saved)


@router.get("", response_model=list[SavedSearchResponse])
async def list_all(ctx: _ViewerCtx, db: DbSession) -> list[SavedSearchResponse]:
    saved = await list_saved_searches(db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id)
    return [_to_response(s) for s in saved]


@router.delete("/{saved_search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(saved_search_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> None:
    await delete_saved_search(
        db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id, saved_search_id=saved_search_id
    )
