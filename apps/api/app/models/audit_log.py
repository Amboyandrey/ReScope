"""The immutable audit trail — one row per privileged action, appended to and never changed."""

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One privileged action: who did what to what, and when."""

    __tablename__ = "audit_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str]
    target_type: Mapped[str]
    target_id: Mapped[str]
    ip: Mapped[str]
    # Named "metadata" at the database level but exposed as `event_metadata` — `metadata` is a
    # reserved attribute name on every declarative model.
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, default=None)
