"""Request/response shapes for a company's notes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateNoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class NoteResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    author_id: uuid.UUID
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}
