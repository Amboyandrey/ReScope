"""Request/response shapes for auth. Password hashes are never on any response schema."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_superadmin: bool
    created_at: datetime

    model_config = {"from_attributes": True}
