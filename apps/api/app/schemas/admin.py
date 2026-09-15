"""Request/response shapes for the platform-operator area."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PlanResponse(BaseModel):
    id: str
    name: str
    profiles_per_month: int
    deep_runs_per_month: int
    max_companies: int
    max_members: int

    model_config = {"from_attributes": True}


class TenantSummaryResponse(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    plan_id: str
    plan_name: str
    status: str
    member_count: int
    spend_this_month_usd: float
    created_at: datetime


class ChangeTenantPlanRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=32)


class PlatformSettingsResponse(BaseModel):
    scraping_paused: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdatePlatformSettingsRequest(BaseModel):
    scraping_paused: bool
