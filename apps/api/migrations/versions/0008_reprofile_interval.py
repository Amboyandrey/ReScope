"""plans.reprofile_interval_days

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15

The last piece docs/PLAN.md §5's "plan-dependent schedule" needed: how many days a plan lets a
company's profile go stale before the scheduler re-runs it. `plans` is reference data (no RLS),
so this is a plain column plus a backfill of the two seeded rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plans", sa.Column("reprofile_interval_days", sa.Integer(), nullable=False, server_default="30")
    )
    op.execute("UPDATE plans SET reprofile_interval_days = 30 WHERE id = 'free'")
    op.execute("UPDATE plans SET reprofile_interval_days = 14 WHERE id = 'pro'")


def downgrade() -> None:
    op.drop_column("plans", "reprofile_interval_days")
