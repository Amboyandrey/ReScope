"""tenant_credentials, usage_events.billed_to

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-16

Part 2 (docs/PLAN.md §12): a workspace can register its own Anthropic and Browser Use keys.
`tenant_credentials` never stores a key in plaintext — `ciphertext`/`nonce`/`wrapped_key` are
envelope-encrypted (app/core/crypto.py); `last4` is the only human-readable trace of the key
itself, enough for a settings page to show which one is registered. Standard SELECT-gated RLS,
no exception — nothing here is ever legitimately read before a tenant is in scope.

`usage_events.billed_to` records which key funded a run, defaulting to the platform's own for
every row written before this column existed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations._rls import enable_tenant_rls

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDER_VALUES = postgresql.ENUM("ANTHROPIC", "BROWSER_USE", name="credential_provider")
_BILLED_TO_VALUES = postgresql.ENUM("PLATFORM", "TENANT", name="usage_billed_to")


def upgrade() -> None:
    bind = op.get_bind()
    _PROVIDER_VALUES.create(bind, checkfirst=True)
    _BILLED_TO_VALUES.create(bind, checkfirst=True)

    op.create_table(
        "tenant_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", postgresql.ENUM(name="credential_provider", create_type=False), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column("last4", sa.String(4), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_tenant_credentials_tenant_provider"),
    )
    enable_tenant_rls("tenant_credentials")

    op.add_column(
        "usage_events",
        sa.Column(
            "billed_to",
            postgresql.ENUM(name="usage_billed_to", create_type=False),
            nullable=False,
            server_default="PLATFORM",
        ),
    )


def downgrade() -> None:
    op.drop_column("usage_events", "billed_to")

    op.execute("DROP POLICY IF EXISTS allow_writes_delete ON tenant_credentials")
    op.execute("DROP POLICY IF EXISTS allow_writes_update ON tenant_credentials")
    op.execute("DROP POLICY IF EXISTS allow_writes_insert ON tenant_credentials")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_credentials")
    op.drop_table("tenant_credentials")

    bind = op.get_bind()
    _BILLED_TO_VALUES.drop(bind, checkfirst=True)
    _PROVIDER_VALUES.drop(bind, checkfirst=True)
