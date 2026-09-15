"""A single-row table of platform-wide operator controls — not tenant data, so no RLS and no
`tenant_id`. The scraping killswitch lives here: a superadmin's own lever, independent of any
tenant's plan or usage, for pausing every scrape across the platform at once (docs/PLAN.md §20)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SETTINGS_ROW_ID = 1


class PlatformSettings(Base):
    """Always exactly one row, `id = SETTINGS_ROW_ID` — enforced by the CHECK constraint below,
    not just convention, so a bug can't silently create a second, ignored settings row."""

    __tablename__ = "platform_settings"
    __table_args__ = (CheckConstraint(f"id = {SETTINGS_ROW_ID}", name="ck_platform_settings_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=SETTINGS_ROW_ID)
    scraping_paused: Mapped[bool] = mapped_column(default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
