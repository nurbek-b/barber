"""barber commission, salon logo and gallery

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "barbers",
        sa.Column("commission_bp", sa.SmallInteger(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_barbers_commission_bp", "barbers", "commission_bp BETWEEN 0 AND 10000"
    )
    op.add_column("bookings", sa.Column("barber_commission_bp", sa.SmallInteger(), nullable=True))
    op.add_column("salon_settings", sa.Column("logo_url", sa.String(length=512), nullable=True))
    op.add_column(
        "salon_settings",
        sa.Column(
            "gallery",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("salon_settings", "gallery")
    op.drop_column("salon_settings", "logo_url")
    op.drop_column("bookings", "barber_commission_bp")
    op.drop_constraint("ck_barbers_commission_bp", "barbers", type_="check")
    op.drop_column("barbers", "commission_bp")
