"""Request/response shapes for a workspace's own provider credentials — the plaintext key is
never a response field, only ever accepted as write-only input."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.models.credential import Provider


class SetCredentialRequest(BaseModel):
    provider: Provider
    api_key: str = Field(min_length=1, max_length=500)
    # Only `CUSTOM` has one — every other provider's endpoint is a constant (docs/PLAN.md §22).
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)

    @model_validator(mode="after")
    def _base_url_matches_provider(self) -> Self:
        if self.provider == Provider.CUSTOM:
            if not self.base_url or not self.base_url.startswith(("http://", "https://")):
                raise ValueError("base_url is required for the custom provider and must be http(s).")
        elif self.base_url is not None:
            raise ValueError("base_url is only accepted for the custom provider.")
        return self


class CredentialResponse(BaseModel):
    id: uuid.UUID
    provider: Provider
    base_url: str | None
    last4: str
    validated_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
