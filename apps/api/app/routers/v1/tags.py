"""A tenant's tags — created once, attached to whichever companies a member likes."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Role
from app.schemas.tag import CreateTagRequest, TagResponse
from app.services.companies import get_company
from app.services.tags import attach_tag, create_tag, delete_tag, detach_tag, list_company_tags, list_tags

tags_router = APIRouter(prefix="/tenants/current/tags", tags=["tags"])
company_tags_router = APIRouter(prefix="/tenants/current/companies/{company_id}/tags", tags=["tags"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]
_MemberCtx = Annotated[TenantCtx, Depends(require_role(Role.MEMBER))]


@tags_router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
async def create(body: CreateTagRequest, ctx: _MemberCtx, db: DbSession) -> TagResponse:
    tag = await create_tag(db, tenant_id=ctx.tenant.id, name=body.name, color=body.color)
    return TagResponse.model_validate(tag)


@tags_router.get("", response_model=list[TagResponse])
async def list_all(ctx: _ViewerCtx, db: DbSession) -> list[TagResponse]:
    return [TagResponse.model_validate(t) for t in await list_tags(db, tenant_id=ctx.tenant.id)]


@tags_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(tag_id: uuid.UUID, ctx: _MemberCtx, db: DbSession) -> None:
    await delete_tag(db, tenant_id=ctx.tenant.id, tag_id=tag_id)


@company_tags_router.get("", response_model=list[TagResponse])
async def list_for_company(company_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> list[TagResponse]:
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)  # 404s if not this tenant's
    tags = await list_company_tags(db, tenant_id=ctx.tenant.id, company_id=company_id)
    return [TagResponse.model_validate(t) for t in tags]


@company_tags_router.put("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def attach(company_id: uuid.UUID, tag_id: uuid.UUID, ctx: _MemberCtx, db: DbSession) -> None:
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)
    await attach_tag(db, tenant_id=ctx.tenant.id, company_id=company_id, tag_id=tag_id)


@company_tags_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach(company_id: uuid.UUID, tag_id: uuid.UUID, ctx: _MemberCtx, db: DbSession) -> None:
    await get_company(db, tenant_id=ctx.tenant.id, company_id=company_id)
    await detach_tag(db, tenant_id=ctx.tenant.id, company_id=company_id, tag_id=tag_id)
