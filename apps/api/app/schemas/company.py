"""Request/response shapes for companies and their extracted profile."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.company import CompetencyKind, OfferingKind, ProfileStatus
from app.models.scrape import ScrapeMode


class CreateCompanyRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=2048, description="A domain or website URL.")
    mode: ScrapeMode = Field(
        default=ScrapeMode.FAST,
        description="'fast' runs Tier 0+1; 'deep' additionally escalates to the visual agent.",
    )


class CompanyResponse(BaseModel):
    id: uuid.UUID
    domain: str
    name: str
    website_url: str
    industry: str | None
    hq_country: str | None
    hq_city: str | None
    employee_range: str | None
    founded_year: int | None
    socials: dict[str, str]
    logo_url: str | None
    overview: str | None
    profile_status: ProfileStatus
    last_profiled_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceItem(BaseModel):
    url: str
    quote: str


class OfferingResponse(BaseModel):
    id: uuid.UUID
    kind: OfferingKind
    name: str
    description: str | None
    category: str | None
    url: str | None
    evidence: list[EvidenceItem]

    model_config = {"from_attributes": True}


class CompetencyResponse(BaseModel):
    id: uuid.UUID
    kind: CompetencyKind
    name: str
    description: str | None
    evidence: list[EvidenceItem]

    model_config = {"from_attributes": True}


class CompanyDetailResponse(CompanyResponse):
    """A company plus everything extracted about it — the profile page's own payload."""

    offerings: list[OfferingResponse]
    competencies: list[CompetencyResponse]


class ScrapeJobResponse(BaseModel):
    id: uuid.UUID
    mode: str
    status: str
    tier_reached: int
    pages_fetched: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class SearchHitResponse(BaseModel):
    company: CompanyResponse
    source_kind: str
    content: str
    distance: float


class SimilarCompanyResponse(BaseModel):
    company: CompanyResponse
    distance: float


class ScrapePageResponse(BaseModel):
    id: uuid.UUID
    url: str
    status_code: int | None
    has_screenshot: bool
    fetched_at: datetime

    model_config = {"from_attributes": True}


class ProfileChangeResponse(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    diff: dict[str, object]
    created_at: datetime

    model_config = {"from_attributes": True}
