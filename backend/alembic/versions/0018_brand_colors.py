"""salon brand colors for the Mini App

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-18 12:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("salon_settings", sa.Column("brand_color", sa.String(7), nullable=True))
    op.add_column("salon_settings", sa.Column("brand_color_2", sa.String(7), nullable=True))


def downgrade() -> None:
    op.drop_column("salon_settings", "brand_color_2")
    op.drop_column("salon_settings", "brand_color")
