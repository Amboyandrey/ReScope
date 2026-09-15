"""Response shape for the audit trail."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    actor_id: uuid.UUID
    action: str
    target_type: str
    target_id: str
    # `serialization_alias` only, not a population alias: an `AuditLog` ORM instance already has
    # its own `.metadata` attribute — every declarative model does, from SQLAlchemy's own base
    # class — so populating from attributes by that name would read the wrong thing. Renders as
    # "metadata" in the JSON response regardless.
    event_metadata: dict[str, Any] | None = Field(default=None, serialization_alias="metadata")
    created_at: datetime

    model_config = {"from_attributes": True}
