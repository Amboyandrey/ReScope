"""A scrape job's own record — what it did, what it cost, and the pages it read along the way."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class ScrapeMode(enum.StrEnum):
    """`FAST` runs Tier 0 discovery then Tier 1 text extraction. `DEEP` additionally escalates to
    the Tier 2 visual browser agent — not built yet (see docs/PLAN.md §21-equivalent, Phase 3)."""

    FAST = "fast"
    DEEP = "deep"


class ScrapeStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ScrapeJob(Base, UUIDPrimaryKeyMixin):
    """One profiling run for one company. `tier_reached` is 0 (discovery only, nothing worth
    extracting was found), 1 (text extraction completed), or 2 (escalated to the visual agent)."""

    __tablename__ = "scrape_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_scrape_jobs_tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column()
    mode: Mapped[ScrapeMode] = mapped_column(Enum(ScrapeMode, name="scrape_mode"))
    status: Mapped[ScrapeStatus] = mapped_column(
        Enum(ScrapeStatus, name="scrape_status"), default=ScrapeStatus.QUEUED
    )
    tier_reached: Mapped[int] = mapped_column(Integer, default=0)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    error: Mapped[str | None] = mapped_column(default=None)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ScrapePage(Base, UUIDPrimaryKeyMixin):
    """One page a scrape job read — the raw artifact behind an extracted fact's evidence URL."""

    __tablename__ = "scrape_pages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["scrape_jobs.tenant_id", "scrape_jobs.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column()
    url: Mapped[str] = mapped_column(String(2048))
    status_code: Mapped[int | None] = mapped_column(Integer, default=None)
    content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    markdown: Mapped[str | None] = mapped_column(default=None)
    # Set only for a page Tier 2's visual agent actually navigated to and screenshotted — Tier 1's
    # own text-only pages leave this null. A storage key (see app/core/storage.py), not the bytes.
    screenshot_key: Mapped[str | None] = mapped_column(String(255), default=None)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProfileChange(Base, UUIDPrimaryKeyMixin):
    """The diff a re-profiling run produced against the company's previous profile."""

    __tablename__ = "profile_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["scrape_jobs.tenant_id", "scrape_jobs.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column()
    job_id: Mapped[uuid.UUID] = mapped_column()
    diff: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
