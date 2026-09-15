"""usage_events, platform_settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-15

`usage_events` is the platform-wide ledger every billable scrape-job step writes to — the same
tokens and cost `scrape_jobs` denormalizes onto itself for its own status view, but here keyed for
aggregation (quota checks sum `usage_events` for a tenant's current calendar month, not
`scrape_jobs`, so a future second billable step — Tier 2, say — needs no new aggregation code).
Composite FK to `scrape_jobs`, standard tenant RLS.

`platform_settings` is the one table with no tenant at all: a fixed single row (enforced by a
CHECK constraint, not just convention) carrying operator-only controls — today just the scraping
killswitch. No RLS; it's gated by `require_superadmin` in application code instead, the same way
ReCore gates its own admin-only flag routes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations._rls import enable_tenant_rls

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USAGE_KIND_VALUES = postgresql.ENUM("PROFILE", "DEEP_PROFILE", name="usage_kind")
_USAGE_KIND = postgresql.ENUM(name="usage_kind", create_type=False)


def upgrade() -> None:
    _USAGE_KIND_VALUES.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", _USAGE_KIND, nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["scrape_jobs.tenant_id", "scrape_jobs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_usage_events_tenant_created", "usage_events", ["tenant_id", "created_at"])
    enable_tenant_rls("usage_events")

    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scraping_paused", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_platform_settings_singleton"),
    )
    op.execute("INSERT INTO platform_settings (id, scraping_paused) VALUES (1, false)")


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.execute("DROP POLICY IF EXISTS allow_writes_delete ON usage_events")
    op.execute("DROP POLICY IF EXISTS allow_writes_update ON usage_events")
    op.execute("DROP POLICY IF EXISTS allow_writes_insert ON usage_events")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON usage_events")
    op.drop_table("usage_events")
    _USAGE_KIND_VALUES.drop(op.get_bind(), checkfirst=True)
