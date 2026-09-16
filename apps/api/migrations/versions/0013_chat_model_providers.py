"""credential_provider.{OPENAI,GEMINI,NEBIUS}

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-16

Part 3 (docs/PLAN.md §16-18): a workspace can register a key for any of these three providers in
addition to Anthropic, to pick which one answers its chat messages. Each `ALTER TYPE ... ADD
VALUE` runs alone, same constraint noted in 0011 and 0012 — nothing here writes a row using any
of these values.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_VALUES = ("OPENAI", "GEMINI", "NEBIUS")


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE credential_provider ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — same accepted trade-off as 0011/0012's own
    # downgrades for an additive enum value.
    pass
