"""reminder confirmation, revisit nudges

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-16 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bookings", sa.Column("client_confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "bookings", sa.Column("revisit_nudged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "salon_settings",
        sa.Column("revisit_after_days", sa.SmallInteger(), server_default="30", nullable=False),
    )
    op.create_check_constraint(
        "ck_salon_settings_revisit_days",
        "salon_settings",
        "revisit_after_days BETWEEN 0 AND 365",
    )


def downgrade() -> None:
    op.drop_constraint("ck_salon_settings_revisit_days", "salon_settings", type_="check")
    op.drop_column("salon_settings", "revisit_after_days")
    op.drop_column("bookings", "revisit_nudged_at")
    op.drop_column("bookings", "client_confirmed_at")
