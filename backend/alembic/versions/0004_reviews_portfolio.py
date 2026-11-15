"""reviews on bookings, barber portfolio

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-15 13:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("review_text", sa.Text(), nullable=True))
    op.add_column(
        "bookings",
        sa.Column("review_hidden", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "ix_bookings_barber_reviews",
        "bookings",
        ["barber_id", "rated_at"],
        unique=False,
        postgresql_where=sa.text("rating IS NOT NULL AND NOT review_hidden"),
    )
    op.add_column(
        "barbers",
        sa.Column(
            "portfolio",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("barbers", "portfolio")
    op.drop_index(
        "ix_bookings_barber_reviews",
        table_name="bookings",
        postgresql_where=sa.text("rating IS NOT NULL AND NOT review_hidden"),
    )
    op.drop_column("bookings", "review_hidden")
    op.drop_column("bookings", "review_text")
