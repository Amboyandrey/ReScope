"""conversations, messages, plans.chat_messages_per_month, usage_kind.CHAT

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-16

Part 2 (docs/PLAN.md §14): retrieval-grounded chat over a tenant's catalogue. `conversations` and
`messages` are personal, owner-scoped like `saved_searches` — the standard SELECT-gated RLS policy
still applies (it checks the row's own `tenant_id`, not ownership; the owner-only view is an
application-level filter in `services/chat.py`, the same split saved searches already use).

`ALTER TYPE ... ADD VALUE` for `usage_kind.CHAT` runs alone in this migration's transaction, same
constraint as 0011's `BROWSER_USE_RUN` — nothing here writes a CHAT row itself.

`usage_events.job_id` becomes nullable here too: a CHAT usage event has no scrape job behind it,
and Postgres's composite foreign key simply isn't checked when one of its columns is null (the
default MATCH SIMPLE behavior) — every existing kind still always sets it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from migrations._rls import enable_tenant_rls

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MESSAGE_ROLE_VALUES = postgresql.ENUM("USER", "ASSISTANT", name="message_role")


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE usage_kind ADD VALUE IF NOT EXISTS 'CHAT'")
    op.alter_column("usage_events", "job_id", nullable=True)

    op.add_column(
        "plans", sa.Column("chat_messages_per_month", sa.Integer(), nullable=False, server_default="0")
    )
    op.execute("UPDATE plans SET chat_messages_per_month = 100 WHERE id = 'free'")
    op.execute("UPDATE plans SET chat_messages_per_month = 2000 WHERE id = 'pro'")

    _MESSAGE_ROLE_VALUES.create(bind, checkfirst=True)

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id"),
    )
    enable_tenant_rls("conversations")

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", postgresql.ENUM(name="message_role", create_type=False), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
    )
    enable_tenant_rls("messages")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS allow_writes_delete ON messages")
    op.execute("DROP POLICY IF EXISTS allow_writes_update ON messages")
    op.execute("DROP POLICY IF EXISTS allow_writes_insert ON messages")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON messages")
    op.drop_table("messages")

    op.execute("DROP POLICY IF EXISTS allow_writes_delete ON conversations")
    op.execute("DROP POLICY IF EXISTS allow_writes_update ON conversations")
    op.execute("DROP POLICY IF EXISTS allow_writes_insert ON conversations")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON conversations")
    op.drop_table("conversations")

    _MESSAGE_ROLE_VALUES.drop(op.get_bind(), checkfirst=True)

    op.drop_column("plans", "chat_messages_per_month")

    op.alter_column("usage_events", "job_id", nullable=False)
    # usage_kind.CHAT is left in place — see 0011's own downgrade docstring for why removing an
    # enum value isn't attempted.
