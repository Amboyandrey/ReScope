"""embeddings

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15

Adds the `vector` extension and the `embeddings` table: one row per company-summary, offering, or
competency, keyed so a re-profile re-embeds by upsert rather than accumulating stale vectors (see
the model's own docstring). `embedding` is fixed at `Vector(1024)` — every tenant embeds through
the same self-hosted Qwen3-Embedding-0.6B model (docs/PLAN.md §1), so unlike ReCore's own
`connector_chunks` (where a workspace picks its own provider and dimension), this column can
actually enforce one.

Standard SELECT-gated RLS, no exception: every read here already runs through `get_tenant_ctx`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from migrations._rls import enable_tenant_rls

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_KIND_VALUES = postgresql.ENUM(
    "COMPANY_SUMMARY", "OFFERING", "COMPETENCY", name="embedding_source_kind"
)
_SOURCE_KIND = postgresql.ENUM(name="embedding_source_kind", create_type=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _SOURCE_KIND_VALUES.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", _SOURCE_KIND, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("tenant_id", "source_kind", "source_id", name="uq_embeddings_tenant_source"),
    )
    op.create_index("ix_embeddings_tenant_company", "embeddings", ["tenant_id", "company_id"])
    # ivfflat needs at least one row to build against and is a poor fit until a table has real
    # volume; an exact scan is fine at ReScope's per-tenant scale (docs/PLAN.md §6). Revisit with
    # an HNSW index (pgvector >= 0.8, `hnsw.iterative_scan = relaxed_order` for filtered recall)
    # once a tenant's embeddings table is large enough for that trade to pay for itself.

    enable_tenant_rls("embeddings")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS allow_writes_delete ON embeddings")
    op.execute("DROP POLICY IF EXISTS allow_writes_update ON embeddings")
    op.execute("DROP POLICY IF EXISTS allow_writes_insert ON embeddings")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON embeddings")
    op.drop_table("embeddings")
    _SOURCE_KIND_VALUES.drop(op.get_bind(), checkfirst=True)
    # The `vector` extension is deliberately left installed — other objects may depend on it, and
    # CREATE EXTENSION IF NOT EXISTS on a later upgrade is a no-op either way (same call ReCore's
    # own knowledge migration makes).
