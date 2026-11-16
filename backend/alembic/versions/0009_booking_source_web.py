"""booking source 'web' (public booking page)

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16 16:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_bookings_booking_source"


def upgrade() -> None:
    op.drop_constraint(op.f(NAME), "bookings", type_="check")
    op.create_check_constraint(
        op.f(NAME), "bookings", "source IN ('miniapp', 'admin', 'bot', 'web')"
    )


def downgrade() -> None:
    op.execute("UPDATE bookings SET source = 'miniapp' WHERE source = 'web'")
    op.drop_constraint(op.f(NAME), "bookings", type_="check")
    op.create_check_constraint(op.f(NAME), "bookings", "source IN ('miniapp', 'admin', 'bot')")
