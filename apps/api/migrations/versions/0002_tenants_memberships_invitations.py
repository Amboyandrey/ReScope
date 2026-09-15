"""tenants, memberships, invitations, audit_logs, plans

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-15

Establishes the tenant boundary itself. `plans` is global reference data, no RLS.

`tenants` is excluded from RLS on purpose, for the same reason ReCore excludes `workspaces`: more
than one legitimate read spans a scope no single-tenant predicate can express. "List my tenants"
runs before any tenant is in scope at all. Worse, previewing or accepting an invitation — by
design, reachable before the caller is a member of the target tenant, sometimes before they even
have an account — needs to read that *other* tenant's name, and no predicate keyed on "the caller's
own tenants" can grant that without also granting it to every other tenant the invitation doesn't
name. It stays scoped by an explicit `id`/`slug` filter joined through the caller's own membership,
or through the invitation's own `tenant_id`, in application code — see `services/tenants.py` and
`services/invitations.py`.

`memberships` keeps the standard SELECT-gated policy from `migrations/_rls.py`, with a predicate
that also matches by `app.user_id` alone: visible either by the currently-scoped tenant or by the
caller's own user id, which is what makes "list my tenants" and "am I a member of this tenant"
work without needing `app.tenant_id` set first.

`invitations` is excluded from RLS for the token/pre-membership reason above, same as ReCore's
own `invitations` table. It stays scoped by an explicit `tenant_id` (or `token_hash`) filter in
application code.

`audit_logs` needs no such exception here, unlike ReCore's: every tenant this app ever writes an
audit row for already has a known id by the time the row is written — `services/tenants.py`
generates a tenant's id in application code (not the mapper's own `default=uuid.uuid4`, which
would only fire at flush time) precisely so `set_tenant_scope` can be called with it before the
tenant row, and its first audit row, are even flushed; every other audited action already runs
through `get_tenant_ctx` first. `app.tenant_id` is therefore always the audited tenant's id by the
time the `INSERT ... RETURNING` runs, which is what the SELECT policy checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations._rls import TENANT_GUC, USER_GUC, disable_tenant_rls, enable_tenant_rls

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres enum values are the Python `Role.StrEnum` members' *names* (uppercase) — how
# SQLAlchemy's Enum type translates by default — not their lowercase `.value`, which is what
# the API actually sends and receives on the wire.
_ROLE_ENUM_VALUES = postgresql.ENUM("VIEWER", "MEMBER", "ADMIN", "OWNER", name="role")
# Bare reference used inside CREATE TABLE, once the type above already exists.
_ROLE_ENUM = postgresql.ENUM(name="role", create_type=False)


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("profiles_per_month", sa.Integer(), nullable=False),
        sa.Column("deep_runs_per_month", sa.Integer(), nullable=False),
        sa.Column("max_companies", sa.Integer(), nullable=False),
        sa.Column("max_members", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "plans",
            sa.column("id", sa.String),
            sa.column("name", sa.String),
            sa.column("profiles_per_month", sa.Integer),
            sa.column("deep_runs_per_month", sa.Integer),
            sa.column("max_companies", sa.Integer),
            sa.column("max_members", sa.Integer),
        ),
        [
            {
                "id": "free",
                "name": "Free",
                "profiles_per_month": 10,
                "deep_runs_per_month": 2,
                "max_companies": 50,
                "max_members": 3,
            },
            {
                "id": "pro",
                "name": "Pro",
                "profiles_per_month": 200,
                "deep_runs_per_month": 40,
                "max_companies": 2000,
                "max_members": 25,
            },
        ],
    )

    _ROLE_ENUM_VALUES.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("plan_id", sa.String(32), sa.ForeignKey("plans.id"), nullable=False, server_default="free"),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("id", name="uq_tenants_id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    op.create_table(
        "memberships",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", _ROLE_ENUM, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", _ROLE_ENUM, nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("invited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint(
            "accepted_at IS NULL OR accepted_at >= created_at", name="ck_invitations_accepted"
        ),
    )
    op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("metadata", postgresql.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_audit_logs_tenant_id", "audit_logs", ["tenant_id"])

    enable_tenant_rls("memberships", select_predicate=f"tenant_id = {TENANT_GUC} OR user_id = {USER_GUC}")
    enable_tenant_rls("audit_logs")


def downgrade() -> None:
    disable_tenant_rls("audit_logs")
    disable_tenant_rls("memberships")
    op.drop_table("audit_logs")
    op.drop_table("invitations")
    op.drop_table("memberships")
    op.drop_table("tenants")
    _ROLE_ENUM_VALUES.drop(op.get_bind(), checkfirst=True)
    op.drop_table("plans")
