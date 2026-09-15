"""An append-only record of what one scrape job's billable work actually cost — never updated,
only ever inserted, so the usage dashboard and quota checks can aggregate without re-deriving
tokens and cost from scrape_jobs each time (whose own tokens_in/out/cost_usd are the same numbers,
denormalized onto the job for its own status view — this table is the platform-wide ledger they
both feed)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class UsageKind(enum.StrEnum):
    """What kind of billable run this event represents — what a plan's own limits are counted
    against (`plans.profiles_per_month` / `plans.deep_runs_per_month`)."""

    PROFILE = "profile"
    DEEP_PROFILE = "deep_profile"


class UsageEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "usage_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["scrape_jobs.tenant_id", "scrape_jobs.id"], ondelete="CASCADE"
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID] = mapped_column()
    kind: Mapped[UsageKind] = mapped_column(Enum(UsageKind, name="usage_kind"))
    model: Mapped[str] = mapped_column(String(120))
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
