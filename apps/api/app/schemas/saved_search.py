"""Request/response shapes for a member's saved searches."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateSavedSearchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    q: str = Field(min_length=1, max_length=500, description="The search query text to re-run.")


class SavedSearchResponse(BaseModel):
    id: uuid.UUID
    name: str
    q: str
    created_at: datetime
