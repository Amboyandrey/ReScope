"""credential_provider.CUSTOM, tenant_credentials.base_url

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-16

Phase 11 (docs/PLAN.md §20-22): a workspace can point chat at its own OpenAI-compatible server —
the `ALTER TYPE ... ADD VALUE` runs alone, same constraint as every enum extension so far (0011,
0012, 0013). `base_url` is nullable and only ever set for `CUSTOM`; every other provider's
endpoint is a constant in app/llm/factory.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_provider ADD VALUE IF NOT EXISTS 'CUSTOM'")
    op.add_column("tenant_credentials", sa.Column("base_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_credentials", "base_url")
    # Postgres has no ALTER TYPE ... DROP VALUE — same accepted trade-off as every prior additive
    # enum-value migration in this project.
