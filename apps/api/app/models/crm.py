"""The light-CRM layer: contacts, notes, tags, and saved searches — everything a member adds by
hand once a company is profiled, as opposed to what scraping extracts."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class Contact(Base, UUIDPrimaryKeyMixin):
    """One person at a tracked company."""

    __tablename__ = "contacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column()
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    title: Mapped[str | None] = mapped_column(String(200), default=None)
    phone: Mapped[str | None] = mapped_column(String(50), default=None)
    linkedin_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    # Free text: "manual", "csv_import", or wherever else a contact came from — never enforced
    # against an enum, since a future source shouldn't need a migration to be named.
    source: Mapped[str] = mapped_column(String(50), default="manual", server_default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Note(Base, UUIDPrimaryKeyMixin):
    """One free-text note left on a company. No edit history — a note is written once."""

    __tablename__ = "notes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column()
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tag(Base, UUIDPrimaryKeyMixin):
    """A tenant-defined label — a tag is scoped to the tenant, not to one company."""

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_tags_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_tags_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    color: Mapped[str] = mapped_column(String(20), default="#71717a", server_default="#71717a")


class CompanyTag(Base):
    """One company/tag pairing — the join table, no id of its own."""

    __tablename__ = "company_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(["tenant_id", "tag_id"], ["tags.tenant_id", "tags.id"], ondelete="CASCADE"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class SavedSearch(Base, UUIDPrimaryKeyMixin):
    """A member's own saved semantic-search query, re-runnable from the companies list."""

    __tablename__ = "saved_searches"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    query: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
