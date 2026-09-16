"""usage_kind.BROWSER_USE_RUN

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-16

Part 2 (docs/PLAN.md §13): a Browser Use Cloud deep-mode run is metered as its own usage kind,
counted against `deep_runs_per_month` exactly like a custom deep run, so admin/usage views can
still tell the two apart.

`ALTER TYPE ... ADD VALUE` can't run in the same transaction as a statement that *uses* the new
value — Postgres locks that down — but adding the value alone is safe inside Alembic's normal
per-migration transaction as long as nothing here tries to write a `BROWSER_USE_RUN` row itself.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE usage_kind ADD VALUE IF NOT EXISTS 'BROWSER_USE_RUN'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — reversing this needs recreating the enum type,
    # which isn't worth the risk for a value that, once used, would need every dependent row
    # rewritten first. Left as a no-op, matching the accepted trade-off for additive enum values.
    pass
