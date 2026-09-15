"""Request/response shapes for tenants and memberships."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.role import Role


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=63)


class TenantResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    plan_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MyTenantResponse(TenantResponse):
    """A tenant in "list mine", with the caller's own role attached."""

    role: Role


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: Role
    created_at: datetime
