"""Request/response shapes for a workspace's own provider credentials — the plaintext key is
never a response field, only ever accepted as write-only input."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.credential import Provider


class SetCredentialRequest(BaseModel):
    provider: Provider
    api_key: str = Field(min_length=1, max_length=500)


class CredentialResponse(BaseModel):
    id: uuid.UUID
    provider: Provider
    last4: str
    validated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
