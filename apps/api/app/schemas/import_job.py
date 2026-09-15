"""Response shape for a CSV import's result."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class ImportResponse(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    row_count: int
    error_count: int
    errors: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}
