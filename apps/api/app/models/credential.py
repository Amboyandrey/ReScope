"""A workspace's own provider API keys — Anthropic and Browser Use — stored envelope-encrypted
(app/core/crypto.py), never in plaintext. Registering one exempts the workspace from that
provider's usage quotas (docs/PLAN.md §9, §12); usage is still metered, marked billed-to-tenant.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class Provider(enum.StrEnum):
    ANTHROPIC = "anthropic"
    BROWSER_USE = "browser_use"
    # Chat-only alternatives to the platform's default Anthropic model (docs/PLAN.md §16) — never
    # used for scraping, which stays on Anthropic for its structured-output and vision needs.
    OPENAI = "openai"
    GEMINI = "gemini"
    NEBIUS = "nebius"


class TenantCredential(Base, UUIDPrimaryKeyMixin):
    """One provider's key for one tenant. `UNIQUE(tenant_id, provider)` — registering a new key
    for a provider replaces the old one rather than creating a second row."""

    __tablename__ = "tenant_credentials"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_tenant_credentials_tenant_provider"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="credential_provider"))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_key: Mapped[bytes] = mapped_column(LargeBinary)
    # The key's last 4 characters, so a settings page can show which key is registered without
    # ever decrypting it just to display it.
    last4: Mapped[str] = mapped_column(String(4))
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
