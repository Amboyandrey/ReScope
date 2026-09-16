"""Request/response shapes for tenants and memberships."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.credential import Provider
from app.models.role import Role
from app.models.tenant import ScrapeProvider


class CreateTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, min_length=1, max_length=63)


class SetScrapeProviderRequest(BaseModel):
    provider: ScrapeProvider


class SetChatModelRequest(BaseModel):
    provider: Provider
    model: str = Field(min_length=1, max_length=200)


class TenantResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    plan_id: str
    scrape_provider: ScrapeProvider
    chat_provider: Provider
    chat_model: str
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
    joined_at: datetime
