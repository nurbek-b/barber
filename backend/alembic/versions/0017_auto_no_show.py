"""auto no-show for visits nobody closed

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-17 09:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "salon_settings",
        sa.Column("auto_no_show_hours", sa.SmallInteger(), server_default="3", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_salon_settings_auto_no_show"),
        "salon_settings",
        "auto_no_show_hours BETWEEN 0 AND 72",
    )
    op.add_column(
        "bookings",
        sa.Column("no_show_auto", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("bookings", "no_show_auto")
    op.drop_constraint(op.f("ck_salon_settings_auto_no_show"), "salon_settings", type_="check")
    op.drop_column("salon_settings", "auto_no_show_hours")
