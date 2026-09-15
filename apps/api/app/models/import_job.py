"""A CSV import's own record — what it was, how far it got, and who ran it."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class ImportKind(enum.StrEnum):
    CONTACTS = "contacts"


class ImportStatus(enum.StrEnum):
    DONE = "done"
    FAILED = "failed"


class Import(Base, UUIDPrimaryKeyMixin):
    """One CSV upload. Rows are processed synchronously (see services/imports.py) — small enough
    a file that this never needed its own background job — so a row is always either DONE or
    FAILED by the time this record exists; there's no PENDING/RUNNING state to poll."""

    __tablename__ = "imports"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[ImportKind] = mapped_column(Enum(ImportKind, name="import_kind"))
    status: Mapped[ImportStatus] = mapped_column(Enum(ImportStatus, name="import_status"))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
