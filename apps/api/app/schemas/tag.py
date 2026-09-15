"""Request/response shapes for tags."""

import uuid

from pydantic import BaseModel, Field


class CreateTagRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    color: str = Field(default="#71717a", max_length=20)


class TagResponse(BaseModel):
    id: uuid.UUID
    name: str
    color: str

    model_config = {"from_attributes": True}
