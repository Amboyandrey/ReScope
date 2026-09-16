"""Response shapes for the catalogue's filter facets — what values exist to filter by, and how
many companies match each, so the UI never offers an option with zero results.
"""

import uuid

from pydantic import BaseModel

from app.models.company import CompanyType
from app.models.company import CompetencyKind as CompetencyKindEnum


class FacetValue(BaseModel):
    value: str
    count: int


class CompanyTypeFacet(BaseModel):
    value: CompanyType
    count: int


class CompetencyKindFacet(BaseModel):
    value: CompetencyKindEnum
    count: int


class TagFacet(BaseModel):
    id: uuid.UUID
    name: str
    color: str
    count: int


class CatalogueFacetsResponse(BaseModel):
    countries: list[FacetValue]
    company_types: list[CompanyTypeFacet]
    industries: list[FacetValue]
    competency_kinds: list[CompetencyKindFacet]
    tags: list[TagFacet]
