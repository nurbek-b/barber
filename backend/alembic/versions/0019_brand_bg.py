"""salon background tone for the Mini App

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-18 18:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("salon_settings", sa.Column("brand_bg", sa.String(7), nullable=True))


def downgrade() -> None:
    op.drop_column("salon_settings", "brand_bg")
