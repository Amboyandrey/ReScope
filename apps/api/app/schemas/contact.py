"""Request/response shapes for a company's contacts."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CreateContactRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=2048)


class UpdateContactRequest(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=2048)


class ContactResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None
    title: str | None
    phone: str | None
    linkedin_url: str | None
    source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
