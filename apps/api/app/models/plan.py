"""A subscription tier — the ceilings a tenant's usage is checked against before work is enqueued."""

from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Plan(Base):
    """One row per tier (`free`, `pro`, ...). Global — no tenant owns a plan."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    profiles_per_month: Mapped[int]
    deep_runs_per_month: Mapped[int]
    max_companies: Mapped[int]
    max_members: Mapped[int]
