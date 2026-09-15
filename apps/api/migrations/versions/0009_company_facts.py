"""company_type, hq_country narrowed to ISO-2, mandatory offering/competency descriptions

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-15

Part 2 (docs/PLAN.md §9-11): a catalogue needs a fixed set of filter values, not free text, so
`company_type` is a closed enum and `hq_country` narrows from a free-text label to ISO 3166-1
alpha-2. Neither column has ever been written by application code yet (extraction never populated
them), so there's no data to migrate for either change.

`offerings.description` and `competencies.description` become NOT NULL — every extracted item is
meant to carry a real, evidence-backed description from now on (it's what gets embedded), and a
bare name is no longer a valid row. Existing NULLs backfill to '' rather than being deleted or
guessed at; the next re-profile (scheduled or manual) is what actually fills them in.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPANY_TYPE_VALUES = postgresql.ENUM(
    "MANUFACTURER",
    "DISTRIBUTOR",
    "SERVICE_PROVIDER",
    "SOFTWARE",
    "CONSULTANCY",
    "AGENCY",
    "RESEARCH",
    "OTHER",
    name="company_type",
)
_COMPANY_TYPE = postgresql.ENUM(name="company_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    _COMPANY_TYPE_VALUES.create(bind, checkfirst=True)

    op.add_column("companies", sa.Column("company_type", _COMPANY_TYPE, nullable=True))
    op.alter_column("companies", "hq_country", type_=sa.String(2), existing_type=sa.String(120))

    op.execute("UPDATE offerings SET description = '' WHERE description IS NULL")
    op.alter_column("offerings", "description", nullable=False, server_default="", existing_type=sa.Text())
    op.execute("UPDATE competencies SET description = '' WHERE description IS NULL")
    op.alter_column("competencies", "description", nullable=False, server_default="", existing_type=sa.Text())


def downgrade() -> None:
    op.alter_column(
        "competencies", "description", nullable=True, server_default=None, existing_type=sa.Text()
    )
    op.alter_column("offerings", "description", nullable=True, server_default=None, existing_type=sa.Text())
    op.alter_column("companies", "hq_country", type_=sa.String(120), existing_type=sa.String(2))
    op.drop_column("companies", "company_type")
    _COMPANY_TYPE_VALUES.drop(op.get_bind(), checkfirst=True)
