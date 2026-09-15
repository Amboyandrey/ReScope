"""One embedded chunk of a company's extracted profile — what semantic and similar-company search
actually run over."""

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Enum, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin

# Fixed at 1024 — Qwen3-Embedding-0.6B's own output size (see docs/PLAN.md §1). Unlike ReCore,
# where a workspace picks its own embedding provider and the column can't declare one dimension,
# every ReScope tenant embeds through the same self-hosted model, so the column enforces it.
EMBEDDING_DIMENSIONS = 1024


class SourceKind(enum.StrEnum):
    """What an embedding row represents. `COMPANY_SUMMARY` is one row per company (its overview),
    used for similar-company search; `OFFERING`/`COMPETENCY` back semantic search over the rest."""

    COMPANY_SUMMARY = "company_summary"
    OFFERING = "offering"
    COMPETENCY = "competency"


class Embedding(Base, UUIDPrimaryKeyMixin):
    """`source_id` is the offering/competency's own id, or the company's own id for a
    `COMPANY_SUMMARY` row — never a second primary key, just whichever row this embedding
    represents. `UNIQUE(tenant_id, source_kind, source_id)` is what makes re-embedding after a
    re-profile an upsert rather than an ever-growing table of stale vectors."""

    __tablename__ = "embeddings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("tenant_id", "source_kind", "source_id", name="uq_embeddings_tenant_source"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column()
    source_kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind, name="embedding_source_kind"))
    source_id: Mapped[uuid.UUID] = mapped_column()
    content: Mapped[str] = mapped_column()
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    model: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
