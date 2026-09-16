"""The tenant boundary: a workspace on its own subdomain, and who belongs to it at what role."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.role import Role


class ScrapeProvider(enum.StrEnum):
    """Which Tier 2 provider a tenant's deep-mode jobs use (docs/PLAN.md §13) — a value inside
    `Tenant.settings`, not its own column, since it's one tenant-chosen option among what will
    likely grow into several free-form preferences over time."""

    CUSTOM = "custom"
    BROWSER_USE_CLOUD = "browser_use_cloud"


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One tenant — every tenant-scoped row elsewhere carries this id, backed by RLS."""

    __tablename__ = "tenants"
    __table_args__ = (UniqueConstraint("id", name="uq_tenants_id"),)

    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True)
    name: Mapped[str]
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), server_default="free")
    status: Mapped[str] = mapped_column(server_default="active")
    settings: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict, server_default="{}")

    @property
    def scrape_provider(self) -> ScrapeProvider:
        value = self.settings.get("scrape_provider")
        if not isinstance(value, str):
            return ScrapeProvider.CUSTOM
        try:
            return ScrapeProvider(value)
        except ValueError:
            return ScrapeProvider.CUSTOM


class Membership(Base):
    """One user's membership in one tenant — a composite key a user can only hold once per tenant."""

    __tablename__ = "memberships"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invitation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An invite to join a tenant at a given role, redeemable once before it expires."""

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("accepted_at IS NULL OR accepted_at >= created_at", name="ck_invitations_accepted"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"))
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    invited_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
