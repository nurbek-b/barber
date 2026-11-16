"""Staff booking management: phone bookings, edits, statuses, drag-and-drop, blocks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
    ValidationAppError,
)
from app.domain.pricing import PriceLine, build_quote
from app.models import Barber, Booking, BookingReminder, Client, SalonSettings
from app.models.enums import (
    ACTIVE_BOOKING_STATUSES,
    ActorType,
    AdminRole,
    BookingKind,
    BookingSource,
    BookingStatus,
    NotificationType,
)
from app.repositories.bookings import BookingRepository
from app.repositories.catalog import BarberRepository
from app.schemas.bookings import (
    AdminBookingCreateIn,
    AdminBookingPatch,
    BlockIn,
    MoveIn,
    StatusChangeIn,
)
from app.services.audit import Actor, AuditService, diff, snapshot
from app.services.availability import Audience, AvailabilityService
from app.services.bonus import BonusService
from app.services.booking_common import (
    EXCLUSION_CONSTRAINT,
    SlotConflictError,
    alternatives,
    cap_bonus,
    is_constraint_violation,
    price_lines,
    set_times,
    snapshot_services,
)
from app.services.branches import BranchService
from app.services.events import BookingEvents, publish, request_rating
from app.services.miniapp_auth import new_referral_code, normalize_phone
from app.services.slot_cache import SlotCache
from app.services.vouchers import VoucherService

TRANSITIONS: dict[BookingStatus, frozenset[BookingStatus]] = {
    BookingStatus.PENDING: frozenset({BookingStatus.CONFIRMED, BookingStatus.CANCELLED}),
    BookingStatus.CONFIRMED: frozenset(
        {BookingStatus.COMPLETED, BookingStatus.CANCELLED, BookingStatus.NO_SHOW}
    ),
    BookingStatus.COMPLETED: frozenset(),
    BookingStatus.CANCELLED: frozenset(),
    BookingStatus.NO_SHOW: frozenset({BookingStatus.CONFIRMED}),  # mistakes happen
}
BARBER_ALLOWED = frozenset({BookingStatus.COMPLETED, BookingStatus.NO_SHOW})


class AdminBookingService:
    def __init__(self, session: AsyncSession, redis: Redis | None, cache: SlotCache) -> None:
        self.session = session
        self.redis = redis
        self.cache = cache
        self.repo = BookingRepository(session)
        self.barbers = BarberRepository(session)
        self.branches = BranchService(session)
        self.availability = AvailabilityService(session, cache)
        self.audit = AuditService(session)
        self.events = BookingEvents(session)

    # ------------------------------------------------------------------ helpers

    async def get(self, branch_id: uuid.UUID, booking_id: uuid.UUID) -> Booking:
        booking = await self.repo.get(branch_id, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found")
        return booking

    @staticmethod
    def _check_version(booking: Booking, version: int) -> None:
        if booking.version != version:
            raise PreconditionFailedError(
                details={"current_version": booking.version}, code="version_mismatch"
            )

    async def _ensure_free(
        self,
        branch_id: uuid.UUID,
        salon: SalonSettings,
        *,
        barber_id: uuid.UUID,
        service_ids: Sequence[uuid.UUID],
        start_at: datetime,
        now: datetime,
        exclude: Sequence[uuid.UUID] = (),
    ) -> None:
        day = start_at.astimezone(ZoneInfo(salon.timezone)).date()
        result = await self.availability.compute(
            branch_id,
            service_ids=service_ids,
            barber_id=barber_id,
            date_from=day,
            date_to=day,
            now=now,
            audience=Audience.STAFF,
            exclude_booking_ids=exclude,
        )
        free = dict(result.days[0].sorted_items()) if result.days else {}
        if barber_id not in free.get(start_at, []):
            raise await self._conflict(branch_id, service_ids, barber_id, start_at, day, now)

    async def _conflict(
        self,
        branch_id: uuid.UUID,
        service_ids: Sequence[uuid.UUID],
        barber_id: uuid.UUID,
        start_at: datetime,
        day: date,
        now: datetime,
    ) -> SlotConflictError:
        slots = []
        if service_ids:
            slots = await alternatives(
                self.availability,
                branch_id,
                service_ids=service_ids,
                barber_id=barber_id,
                around=start_at,
                day=day,
                now=now,
                audience=Audience.STAFF,
            )
        return SlotConflictError(
            details={"alternatives": [slot.model_dump(mode="json") for slot in slots]}
        )

    async def _flush_or_conflict(
        self,
        branch_id: uuid.UUID,
        tz: ZoneInfo,
        service_ids: Sequence[uuid.UUID],
        barber_id: uuid.UUID,
        start_at: datetime,
        now: datetime,
    ) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if is_constraint_violation(exc, EXCLUSION_CONSTRAINT):
                await self.cache.bump([barber_id])
                raise await self._conflict(
                    branch_id,
                    service_ids,
                    barber_id,
                    start_at,
                    start_at.astimezone(tz).date(),
                    now,
                ) from exc
            raise
        except StaleDataError as exc:
            await self.session.rollback()
            raise PreconditionFailedError(code="version_mismatch") from exc

    async def _client_for(self, branch_id: uuid.UUID, data: AdminBookingCreateIn) -> Client:
        if data.client_id is not None:
            client = await self.session.get(Client, data.client_id)
            if client is None or client.branch_id != branch_id:
                raise ValidationAppError("Client not found", code="client_not_found")
            return client
        if data.client is None:  # guaranteed by the schema validator
            raise ValidationAppError("client is required", code="client_required")
        phone = normalize_phone(data.client.phone)
        existing = await self.session.scalar(
            select(Client).where(Client.branch_id == branch_id, Client.phone == phone).limit(1)
        )
        if existing is not None:
            return existing
        client = Client(
            branch_id=branch_id,
            name=data.client.name.strip(),
            phone=phone,
            referral_code=new_referral_code(),
        )
        self.session.add(client)
        await self.session.flush()
        return client

    # ------------------------------------------------------------------ queries

    async def search(
        self,
        branch_id: uuid.UUID,
        *,
        date_from: datetime | None,
        date_to: datetime | None,
        barber_ids: Sequence[uuid.UUID] | None,
        statuses: Sequence[BookingStatus] | None,
        client_id: uuid.UUID | None,
        include_blocks: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Booking], int]:
        return await self.repo.search(
            branch_id,
            date_from=date_from,
            date_to=date_to,
            barber_ids=barber_ids,
            statuses=statuses,
            client_id=client_id,
            include_blocks=include_blocks,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------ commands

    async def create(
        self, branch_id: uuid.UUID, data: AdminBookingCreateIn, actor: Actor, now: datetime
    ) -> Booking:
        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        barber = await self.barbers.get(branch_id, data.barber_id)
        if barber is None or not barber.is_active:
            raise ValidationAppError("Barber not found", code="barber_not_found")
        start_at = data.start_at.astimezone(UTC)
        if not data.ignore_schedule:
            await self._ensure_free(
                branch_id,
                salon,
                barber_id=barber.id,
                service_ids=data.service_ids,
                start_at=start_at,
                now=now,
            )
        client = await self._client_for(branch_id, data)
        if client.is_blocked:
            raise ConflictError("Client is blocked", code="client_blocked")
        lines = await price_lines(self.session, barber.id, data.service_ids)
        quote = build_quote(lines, bonus_balance=0, max_spend_bp=0, bonus_enabled=False)
        booking = Booking(
            branch_id=branch_id,
            client_id=client.id,
            barber_id=barber.id,
            kind=BookingKind.APPOINTMENT,
            status=data.status,
            source=BookingSource.ADMIN,
            subtotal=quote.subtotal,
            bonus_spent=0,
            total_due=quote.subtotal,
            comment=data.comment,
            admin_note=data.admin_note,
            created_by_admin_id=actor.id,
            services=snapshot_services(quote),
        )
        set_times(booking, start_at, quote.duration_min, salon.buffer_min)
        self.repo.add(booking)
        barber_id, service_ids = barber.id, list(data.service_ids)
        await self._flush_or_conflict(branch_id, tz, service_ids, barber_id, start_at, now)
        self.audit.record(actor, "booking.create", "booking", booking.id, after=snapshot(booking))
        notification = await self.events.emit(
            NotificationType.BOOKING_CREATED, booking, salon, notify_client=data.notify_client
        )
        await self.session.commit()
        await self.cache.bump([booking.barber_id])
        await publish(self.redis, notification)
        return booking

    async def patch(
        self,
        branch_id: uuid.UUID,
        booking_id: uuid.UUID,
        data: AdminBookingPatch,
        actor: Actor,
        now: datetime,
    ) -> Booking:
        booking = await self.get(branch_id, booking_id)
        self._check_version(booking, data.version)
        if booking.kind is BookingKind.BLOCK:
            raise ValidationAppError("Use the blocks API for blocks", code="is_block")
        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        before = {**snapshot(booking), "services": [snapshot(s) for s in booking.services]}

        if data.services is not None:
            if booking.status in (BookingStatus.CANCELLED, BookingStatus.NO_SHOW):
                raise ConflictError("Booking is closed", code="booking_closed")
            base = {
                line.service_id: line
                for line in await price_lines(
                    self.session, booking.barber_id, [item.service_id for item in data.services]
                )
            }
            lines = [
                PriceLine(
                    service_id=item.service_id,
                    name=base[item.service_id].name,
                    duration_min=base[item.service_id].duration_min,
                    price=item.price if item.price is not None else base[item.service_id].price,
                )
                for item in data.services
            ]
            quote = build_quote(lines, bonus_balance=0, max_spend_bp=0, bonus_enabled=False)
            booking.services.clear()
            await self.session.flush()
            booking.services.extend(snapshot_services(quote))
            booking.subtotal = quote.subtotal
            await cap_bonus(self.session, booking, now)
            set_times(booking, booking.start_at, quote.duration_min, salon.buffer_min)

        for field in ("comment", "admin_note", "payment_method", "paid_amount"):
            if field in data.model_fields_set:
                setattr(booking, field, getattr(data, field))

        service_ids = [s.service_id for s in booking.services if s.service_id]
        barber_id, start_at = booking.barber_id, booking.start_at
        await self._flush_or_conflict(branch_id, tz, service_ids, barber_id, start_at, now)
        after = {**snapshot(booking), "services": [snapshot(s) for s in booking.services]}
        old, new = diff(before, after)
        if new:
            self.audit.record(actor, "booking.update", "booking", booking.id, before=old, after=new)
        await self.session.commit()
        await self.cache.bump([booking.barber_id])
        return booking

    async def change_status(
        self,
        branch_id: uuid.UUID,
        booking_id: uuid.UUID,
        data: StatusChangeIn,
        actor: Actor,
        role: AdminRole,
        own_barber_id: uuid.UUID | None,
        now: datetime,
    ) -> Booking:
        booking = await self.get(branch_id, booking_id)
        if role is AdminRole.BARBER and (
            booking.barber_id != own_barber_id or data.status not in BARBER_ALLOWED
        ):
            raise ForbiddenError()
        self._check_version(booking, data.version)
        if booking.kind is BookingKind.BLOCK:
            raise ValidationAppError("Use the blocks API for blocks", code="is_block")
        if data.status not in TRANSITIONS[booking.status]:
            raise ConflictError(
                f"Cannot change status from {booking.status.value} to {data.status.value}",
                code="invalid_transition",
                details={"allowed": sorted(s.value for s in TRANSITIONS[booking.status])},
            )
        if data.status is BookingStatus.COMPLETED:
            if data.payment_method is None and booking.payment_method is None:
                raise ValidationAppError("payment_method is required", code="payment_required")
            if booking.start_at > now:
                raise ValidationAppError(
                    "A future booking cannot be completed", code="booking_in_future"
                )
        salon = await self.branches.settings(branch_id)
        previous = booking.status
        booking.status = data.status
        event = NotificationType.BOOKING_STATUS_CHANGED
        extra: dict[str, Any] = {}
        if data.status is BookingStatus.COMPLETED:
            booking.payment_method = data.payment_method or booking.payment_method
            # certificates / subscription visits are not money paid today
            booking.paid_amount = (
                data.paid_amount
                if data.paid_amount is not None
                else max(0, booking.total_due - booking.voucher_amount)
            )
            booking.completed_at = now
            barber = await self.session.get(Barber, booking.barber_id)
            booking.barber_commission_bp = barber.commission_bp if barber else 0
        elif data.status is BookingStatus.CANCELLED:
            booking.cancelled_by = ActorType.ADMIN
            booking.cancelled_at = now
            booking.cancel_reason = data.reason
            event = NotificationType.BOOKING_CANCELLED
            extra = {"cancelled_by": ActorType.ADMIN.value, "reason": data.reason}
        elif data.status is BookingStatus.NO_SHOW:
            client = await self.session.get(Client, booking.client_id)
            if client is not None:
                client.no_show_count += 1
        elif previous is BookingStatus.NO_SHOW:
            client = await self.session.get(Client, booking.client_id)
            if client is not None and client.no_show_count > 0:
                client.no_show_count -= 1
            # bonuses were returned at no-show: the revived booking is paid in full
            booking.bonus_spent = 0
            booking.total_due = booking.subtotal
        try:
            await self.session.flush()
        except IntegrityError as exc:  # no_show → confirmed into an occupied slot
            await self.session.rollback()
            if is_constraint_violation(exc, EXCLUSION_CONSTRAINT):
                raise SlotConflictError(details={"alternatives": []}) from exc
            raise
        bonuses = BonusService(self.session)
        if data.status in (BookingStatus.CANCELLED, BookingStatus.NO_SHOW):
            await bonuses.refund_for_booking(booking, now)
            await VoucherService(self.session).release_for_booking(booking)
        elif data.status is BookingStatus.COMPLETED:
            await bonuses.on_completed(booking, now)
            await request_rating(self.session, booking, now)
        self.audit.record(
            actor,
            "booking.status",
            "booking",
            booking.id,
            before={"status": previous.value},
            after={
                "status": booking.status.value,
                "paid_amount": booking.paid_amount,
                "payment_method": booking.payment_method.value if booking.payment_method else None,
                "reason": data.reason,
            },
        )
        notification = await self.events.emit(event, booking, salon, **extra)
        await self.session.commit()
        await self.cache.bump([booking.barber_id])
        await publish(self.redis, notification)
        return booking

    async def move(
        self,
        branch_id: uuid.UUID,
        booking_id: uuid.UUID,
        data: MoveIn,
        actor: Actor,
        now: datetime,
    ) -> Booking:
        """Drag-and-drop in the calendar: new time and/or barber, same services."""
        booking = await self.get(branch_id, booking_id)
        self._check_version(booking, data.version)
        if booking.status not in ACTIVE_BOOKING_STATUSES:
            raise ConflictError("Only active bookings can be moved", code="booking_not_active")
        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        target_barber = data.barber_id or booking.barber_id
        start_at = data.start_at.astimezone(UTC)
        service_ids = [s.service_id for s in booking.services if s.service_id]

        if booking.kind is BookingKind.APPOINTMENT and not data.ignore_schedule:
            await self._ensure_free(
                branch_id,
                salon,
                barber_id=target_barber,
                service_ids=service_ids,
                start_at=start_at,
                now=now,
                exclude=[booking.id],
            )
        old_start, old_barber = booking.start_at, booking.barber_id
        if target_barber != booking.barber_id and booking.kind is BookingKind.APPOINTMENT:
            barber = await self.barbers.get(branch_id, target_barber)
            if barber is None or not barber.is_active:
                raise ValidationAppError("Barber not found", code="barber_not_found")
            lines = await price_lines(self.session, target_barber, service_ids)
            quote = build_quote(lines, bonus_balance=0, max_spend_bp=0, bonus_enabled=False)
            booking.services.clear()
            await self.session.flush()
            booking.services.extend(snapshot_services(quote))
            booking.subtotal = quote.subtotal
            await cap_bonus(self.session, booking, now)
            duration = quote.duration_min
        else:
            duration = int((booking.end_at - booking.start_at).total_seconds() // 60)
        booking.barber_id = target_barber
        buffer = salon.buffer_min if booking.kind is BookingKind.APPOINTMENT else 0
        set_times(booking, start_at, duration, buffer)
        await self._flush_or_conflict(branch_id, tz, service_ids, target_barber, start_at, now)
        await self.session.execute(
            delete(BookingReminder).where(BookingReminder.booking_id == booking.id)
        )
        self.audit.record(
            actor,
            "booking.move",
            "booking",
            booking.id,
            before={"start_at": old_start.isoformat(), "barber_id": str(old_barber)},
            after={"start_at": booking.start_at.isoformat(), "barber_id": str(target_barber)},
        )
        notification = None
        if booking.kind is BookingKind.APPOINTMENT:
            notification = await self.events.emit(
                NotificationType.BOOKING_RESCHEDULED, booking, salon, old_start_at=old_start
            )
        await self.session.commit()
        await self.cache.bump({old_barber, target_barber})
        if notification is not None:
            await publish(self.redis, notification)
        return booking

    async def create_block(
        self, branch_id: uuid.UUID, data: BlockIn, actor: Actor, now: datetime
    ) -> Booking:
        salon = await self.branches.settings(branch_id)
        barber = await self.barbers.get(branch_id, data.barber_id)
        if barber is None:
            raise ValidationAppError("Barber not found", code="barber_not_found")
        block = Booking(
            branch_id=branch_id,
            barber_id=barber.id,
            kind=BookingKind.BLOCK,
            status=BookingStatus.CONFIRMED,
            source=BookingSource.ADMIN,
            start_at=data.start_at,
            end_at=data.end_at,
            blocked_until=data.end_at,
            subtotal=0,
            bonus_spent=0,
            total_due=0,
            admin_note=data.comment,
            created_by_admin_id=actor.id,
            services=[],
        )
        self.repo.add(block)
        await self._flush_or_conflict(
            branch_id, ZoneInfo(salon.timezone), [], barber.id, data.start_at, now
        )
        self.audit.record(actor, "block.create", "booking", block.id, after=snapshot(block))
        await self.session.commit()
        await self.cache.bump([barber.id])
        return block

    async def delete_block(self, branch_id: uuid.UUID, block_id: uuid.UUID, actor: Actor) -> None:
        block = await self.get(branch_id, block_id)
        if block.kind is not BookingKind.BLOCK:
            raise ValidationAppError("Not a block", code="not_a_block")
        if block.status is BookingStatus.CANCELLED:
            return
        block.status = BookingStatus.CANCELLED
        self.audit.record(actor, "block.delete", "booking", block.id, before=snapshot(block))
        await self.session.commit()
        await self.cache.bump([block.barber_id])
