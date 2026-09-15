"""scrape_pages screenshot_key

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-15

Adds the column Tier 2's visual agent needs to point a page's evidence at the screenshot it
actually navigated — set only for pages visited during a deep run; Tier 1's own text-only pages
leave it null. See app/scraping/visual_agent.py and app/core/storage.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scrape_pages", sa.Column("screenshot_key", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("scrape_pages", "screenshot_key")
