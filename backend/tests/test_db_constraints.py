"""The exclusion constraint is the last line of defense against double booking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Barber, Booking, Branch, Client
from app.models.enums import BookingKind, BookingStatus

T0 = datetime(2026, 12, 1, 6, 0, tzinfo=UTC)  # 12:00 in Bishkek


async def _setup(session: AsyncSession, branch: Branch) -> tuple[Barber, Barber, Client]:
    first = Barber(branch_id=branch.id, name="A")
    second = Barber(branch_id=branch.id, name="B")
    client = Client(branch_id=branch.id, name="C", referral_code="testcode")
    session.add_all([first, second, client])
    await session.commit()
    return first, second, client


def _booking(
    barber: Barber,
    client: Client | None,
    start: datetime,
    minutes: int,
    buffer: int = 0,
    status: BookingStatus = BookingStatus.CONFIRMED,
    kind: BookingKind = BookingKind.APPOINTMENT,
) -> Booking:
    return Booking(
        branch_id=barber.branch_id,
        barber_id=barber.id,
        client_id=client.id if client else None,
        kind=kind,
        status=status,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        blocked_until=start + timedelta(minutes=minutes + buffer),
        subtotal=100_000,
        bonus_spent=0,
        total_due=100_000,
    )


async def test_overlap_is_rejected(session: AsyncSession, branch: Branch) -> None:
    barber, _, client = await _setup(session, branch)
    session.add(_booking(barber, client, T0, 60))
    await session.commit()

    session.add(_booking(barber, client, T0 + timedelta(minutes=30), 30))
    with pytest.raises(IntegrityError, match="ex_bookings_no_overlap"):
        await session.commit()
    await session.rollback()


async def test_adjacent_bookings_are_allowed(session: AsyncSession, branch: Branch) -> None:
    barber, _, client = await _setup(session, branch)
    session.add(_booking(barber, client, T0, 60))
    session.add(_booking(barber, client, T0 + timedelta(minutes=60), 60))
    await session.commit()


async def test_buffer_is_part_of_the_blocked_range(session: AsyncSession, branch: Branch) -> None:
    barber, _, client = await _setup(session, branch)
    session.add(_booking(barber, client, T0, 60, buffer=10))
    await session.commit()
    session.add(_booking(barber, client, T0 + timedelta(minutes=65), 30))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_cancelled_booking_frees_the_slot(session: AsyncSession, branch: Branch) -> None:
    barber, _, client = await _setup(session, branch)
    session.add(_booking(barber, client, T0, 60, status=BookingStatus.CANCELLED))
    session.add(_booking(barber, client, T0, 60, status=BookingStatus.NO_SHOW))
    session.add(_booking(barber, client, T0, 60))
    await session.commit()


async def test_other_barber_same_time(session: AsyncSession, branch: Branch) -> None:
    first, second, client = await _setup(session, branch)
    session.add(_booking(first, client, T0, 60))
    session.add(_booking(second, client, T0, 60))
    await session.commit()


async def test_block_conflicts_with_appointment(session: AsyncSession, branch: Branch) -> None:
    barber, _, client = await _setup(session, branch)
    session.add(_booking(barber, None, T0, 120, kind=BookingKind.BLOCK))
    await session.commit()
    session.add(_booking(barber, client, T0 + timedelta(minutes=90), 60))
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_total_due_must_match(session: AsyncSession, branch: Branch) -> None:
    barber, _, client = await _setup(session, branch)
    booking = _booking(barber, client, T0, 60)
    booking.bonus_spent = 10_000  # total_due not updated -> CHECK fails
    session.add(booking)
    with pytest.raises(IntegrityError, match="total_due"):
        await session.commit()
    await session.rollback()


async def test_appointment_requires_client(session: AsyncSession, branch: Branch) -> None:
    barber, _, _ = await _setup(session, branch)
    session.add(_booking(barber, None, T0, 60))
    with pytest.raises(IntegrityError, match="client_required"):
        await session.commit()
    await session.rollback()
