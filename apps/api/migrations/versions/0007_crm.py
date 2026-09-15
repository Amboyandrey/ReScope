"""contacts, notes, tags, company_tags, saved_searches, imports

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-15

The light-CRM layer from docs/PLAN.md §1 — everything a member adds by hand once a company is
profiled. `contacts` and `notes` get the usual composite FK to `companies`. `tags` carries its own
`UNIQUE(tenant_id, id)` so `company_tags` can declare a composite FK to *it* the same way, on top
of the one it already needs to `companies` — a join row can't point a tag or a company at another
tenant's row. `saved_searches` and `imports` are plain tenant-scoped tables with no children.

Standard SELECT-gated RLS on every table, no exception — nothing here is ever read before a
tenant is in scope.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations._rls import enable_tenant_rls

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMPORT_KIND_VALUES = postgresql.ENUM("CONTACTS", name="import_kind")
_IMPORT_STATUS_VALUES = postgresql.ENUM("DONE", "FAILED", name="import_status")
_IMPORT_KIND = postgresql.ENUM(name="import_kind", create_type=False)
_IMPORT_STATUS = postgresql.ENUM(name="import_status", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    _IMPORT_KIND_VALUES.create(bind, checkfirst=True)
    _IMPORT_STATUS_VALUES.create(bind, checkfirst=True)

    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(120), nullable=False),
        sa.Column("last_name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("linkedin_url", sa.String(2048), nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_contacts_tenant_company", "contacts", ["tenant_id", "company_id"])

    op.create_table(
        "notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_notes_tenant_company", "notes", ["tenant_id", "company_id"])

    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("color", sa.String(20), nullable=False, server_default="#71717a"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tags_tenant_name"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tags_tenant_id"),
    )

    op.create_table(
        "company_tags",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id", "tag_id"], ["tags.tenant_id", "tags.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "saved_searches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("query", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", _IMPORT_KIND, nullable=False),
        sa.Column("status", _IMPORT_STATUS, nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    for table in ("contacts", "notes", "tags", "company_tags", "saved_searches", "imports"):
        enable_tenant_rls(table)


def downgrade() -> None:
    for table in ("imports", "saved_searches", "company_tags", "tags", "notes", "contacts"):
        op.execute(f"DROP POLICY IF EXISTS allow_writes_delete ON {table}")
        op.execute(f"DROP POLICY IF EXISTS allow_writes_update ON {table}")
        op.execute(f"DROP POLICY IF EXISTS allow_writes_insert ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("imports")
    op.drop_table("saved_searches")
    op.drop_table("company_tags")
    op.drop_table("tags")
    op.drop_table("notes")
    op.drop_table("contacts")
    bind = op.get_bind()
    _IMPORT_STATUS_VALUES.drop(bind, checkfirst=True)
    _IMPORT_KIND_VALUES.drop(bind, checkfirst=True)
