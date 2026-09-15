"""companies, offerings, competencies, scrape jobs

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-15

Introduces the first tenant-scoped tables with children: `companies` carries a `UNIQUE(tenant_id,
id)` constraint precisely so `offerings`, `competencies`, and `scrape_jobs` can declare a composite
foreign key back to it — `FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id,
id)` — which makes a row pointing at another tenant's company a constraint violation, not just an
application bug (see docs/PLAN.md §3). `scrape_jobs` gets the same `UNIQUE(tenant_id, id)` so
`scrape_pages` and `profile_changes` can do the same one level down.

Every table here gets the standard SELECT-gated RLS policy with no exception: unlike `tenants` and
`invitations`, nothing here is ever legitimately read before a single tenant is in scope — every
read runs through `get_tenant_ctx` first, and the one exception (the arq scraper job, which has no
HTTP request to run that dependency chain) sets `app.tenant_id` itself before touching any of
these tables, the same discipline ReCore's own connector-indexing worker follows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations._rls import enable_tenant_rls

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name)


def _bare(name: str) -> postgresql.ENUM:
    """A reference to an enum type that already exists, for use inside `create_table`."""
    return postgresql.ENUM(name=name, create_type=False)


_PROFILE_STATUS = _enum("profile_status", "PENDING", "SCRAPING", "DONE", "FAILED")
_OFFERING_KIND = _enum("offering_kind", "PRODUCT", "SERVICE")
_COMPETENCY_KIND = _enum(
    "competency_kind", "CAPABILITY", "TECHNOLOGY", "CERTIFICATION", "INDUSTRY_SERVED", "PARTNERSHIP"
)
_SCRAPE_MODE = _enum("scrape_mode", "FAST", "DEEP")
_SCRAPE_STATUS = _enum("scrape_status", "QUEUED", "RUNNING", "DONE", "FAILED")

_ENUMS = [_PROFILE_STATUS, _OFFERING_KIND, _COMPETENCY_KIND, _SCRAPE_MODE, _SCRAPE_STATUS]


def upgrade() -> None:
    bind = op.get_bind()
    for e in _ENUMS:
        e.create(bind, checkfirst=True)

    op.create_table(
        "companies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("website_url", sa.String(2048), nullable=False),
        sa.Column("industry", sa.String(120), nullable=True),
        sa.Column("hq_country", sa.String(120), nullable=True),
        sa.Column("hq_city", sa.String(120), nullable=True),
        sa.Column("employee_range", sa.String(32), nullable=True),
        sa.Column("founded_year", sa.Integer(), nullable=True),
        sa.Column("socials", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("logo_url", sa.String(2048), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("profile_status", _bare("profile_status"), nullable=False, server_default="PENDING"),
        sa.Column("last_profiled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "domain", name="uq_companies_tenant_domain"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_companies_tenant_id"),
    )
    op.create_index("ix_companies_tenant_id", "companies", ["tenant_id"])

    op.create_table(
        "offerings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", _bare("offering_kind"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(120), nullable=True),
        sa.Column("url", sa.String(2048), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
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
    op.create_index("ix_offerings_tenant_company", "offerings", ["tenant_id", "company_id"])

    op.create_table(
        "competencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", _bare("competency_kind"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default="[]"),
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
    op.create_index("ix_competencies_tenant_company", "competencies", ["tenant_id", "company_id"])

    op.create_table(
        "scrape_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", _bare("scrape_mode"), nullable=False),
        sa.Column("status", _bare("scrape_status"), nullable=False, server_default="QUEUED"),
        sa.Column("tier_reached", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_scrape_jobs_tenant_id"),
    )
    op.create_index("ix_scrape_jobs_tenant_company", "scrape_jobs", ["tenant_id", "company_id"])

    op.create_table(
        "scrape_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("markdown", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["scrape_jobs.tenant_id", "scrape_jobs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_scrape_pages_tenant_job", "scrape_pages", ["tenant_id", "job_id"])

    op.create_table(
        "profile_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("diff", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "company_id"], ["companies.tenant_id", "companies.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "job_id"], ["scrape_jobs.tenant_id", "scrape_jobs.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_profile_changes_tenant_company", "profile_changes", ["tenant_id", "company_id"])

    for table in ("companies", "offerings", "competencies", "scrape_jobs", "scrape_pages", "profile_changes"):
        enable_tenant_rls(table)


def downgrade() -> None:
    for table in ("profile_changes", "scrape_pages", "scrape_jobs", "competencies", "offerings", "companies"):
        op.execute(f"DROP POLICY IF EXISTS allow_writes_delete ON {table}")
        op.execute(f"DROP POLICY IF EXISTS allow_writes_update ON {table}")
        op.execute(f"DROP POLICY IF EXISTS allow_writes_insert ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_table("profile_changes")
    op.drop_table("scrape_pages")
    op.drop_table("scrape_jobs")
    op.drop_table("competencies")
    op.drop_table("offerings")
    op.drop_table("companies")
    bind = op.get_bind()
    for e in reversed(_ENUMS):
        e.drop(bind, checkfirst=True)
