"""A company being tracked: what's known about it, and where profiling currently stands."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class ProfileStatus(enum.StrEnum):
    """Where a company's profile currently stands — driven by its most recent scrape job."""

    PENDING = "pending"
    SCRAPING = "scraping"
    DONE = "done"
    FAILED = "failed"


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One tracked company. `UNIQUE(tenant_id, id)` exists so child tables — offerings,
    competencies, scrape_jobs — can declare a composite foreign key back to this row scoped by
    tenant, the same pattern `tenants` uses for its own children (see docs/PLAN.md §3)."""

    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "domain", name="uq_companies_tenant_domain"),
        UniqueConstraint("tenant_id", "id", name="uq_companies_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    domain: Mapped[str] = mapped_column(String(253))
    name: Mapped[str] = mapped_column(String(200))
    website_url: Mapped[str] = mapped_column(String(2048))
    industry: Mapped[str | None] = mapped_column(String(120), default=None)
    hq_country: Mapped[str | None] = mapped_column(String(120), default=None)
    hq_city: Mapped[str | None] = mapped_column(String(120), default=None)
    employee_range: Mapped[str | None] = mapped_column(String(32), default=None)
    founded_year: Mapped[int | None] = mapped_column(Integer, default=None)
    socials: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    logo_url: Mapped[str | None] = mapped_column(String(2048), default=None)
    overview: Mapped[str | None] = mapped_column(default=None)
    profile_status: Mapped[ProfileStatus] = mapped_column(
        Enum(ProfileStatus, name="profile_status"), default=ProfileStatus.PENDING
    )
    last_profiled_at: Mapped[datetime | None] = mapped_column(default=None)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class EvidenceMixin:
    """`evidence` is a list of `{"url": ..., "quote": ...}` — where an extracted fact came from,
    so a profile built by an LLM can be checked against the page it was read off of."""

    evidence: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list, server_default="[]")


class OfferingKind(enum.StrEnum):
    PRODUCT = "product"
    SERVICE = "service"


class Offering(Base, UUIDPrimaryKeyMixin, TimestampMixin, EvidenceMixin):
    """One product or service a company offers, as extracted from its own website."""

    __tablename__ = "offerings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[OfferingKind] = mapped_column(Enum(OfferingKind, name="offering_kind"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(default=None)
    category: Mapped[str | None] = mapped_column(String(120), default=None)
    url: Mapped[str | None] = mapped_column(String(2048), default=None)


class CompetencyKind(enum.StrEnum):
    CAPABILITY = "capability"
    TECHNOLOGY = "technology"
    CERTIFICATION = "certification"
    INDUSTRY_SERVED = "industry_served"
    PARTNERSHIP = "partnership"


class Competency(Base, UUIDPrimaryKeyMixin, TimestampMixin, EvidenceMixin):
    """One capability, technology, certification, served industry, or partnership a company has."""

    __tablename__ = "competencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[CompetencyKind] = mapped_column(Enum(CompetencyKind, name="competency_kind"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(default=None)
