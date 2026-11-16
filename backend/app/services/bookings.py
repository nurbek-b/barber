"""Client (Mini App) booking flow: hold → confirm → cancel / reschedule."""

from __future__ import annotations

import base64
import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppError,
    ConflictError,
    NotFoundError,
    RateLimitedError,
    ValidationAppError,
)
from app.core.redis import hit_rate_limit
from app.domain.pricing import Quote
from app.domain.slots import local_day_bounds, pick_least_loaded
from app.models import Barber, Booking, BookingReminder, Client, SalonSettings
from app.models.enums import (
    ACTIVE_BOOKING_STATUSES,
    ActorType,
    BookingKind,
    BookingSource,
    BookingStatus,
    NotificationType,
)
from app.repositories.bookings import BookingRepository
from app.repositories.catalog import BarberRepository
from app.repositories.schedule import BookingReadRepository
from app.services.audit import Actor, AuditService, snapshot
from app.services.availability import Audience, AvailabilityService
from app.services.bonus import BonusService
from app.services.booking_common import (
    EXCLUSION_CONSTRAINT,
    IDEMPOTENCY_INDEX,
    CreatedBooking,
    SlotConflictError,
    alternatives,
    cap_bonus,
    is_constraint_violation,
    quote_for,
    set_times,
    snapshot_services,
)
from app.services.branches import BranchService
from app.services.events import BookingEvents, publish
from app.services.holds import HOLD_TTL, Hold, HoldStore, HoldUnavailableError
from app.services.promo import PromoService
from app.services.slot_cache import SlotCache

HOLD_RATE = (20, 60)
BOOKING_RATE_MINUTE = (5, 60)
BOOKING_RATE_DAY = (20, 86_400)
IDEMPOTENCY_TTL = 86_400


class HoldsUnavailableError(AppError):
    status_code = 503
    code = "holds_unavailable"
    message = "Booking is temporarily unavailable, please retry"


@dataclass(frozen=True, slots=True)
class PlacedHold:
    hold: Hold
    barber: Barber
    quote: Quote


def can_change(booking: Booking, now: datetime, min_hours: int) -> bool:
    return (
        booking.kind is BookingKind.APPOINTMENT
        and booking.status in ACTIVE_BOOKING_STATUSES
        and booking.start_at - now >= timedelta(hours=min_hours)
    )


def encode_cursor(booking: Booking) -> str:
    raw = f"{booking.start_at.timestamp()}|{booking.id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        ts, _, booking_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromtimestamp(float(ts), UTC), uuid.UUID(booking_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationAppError("Invalid cursor", code="invalid_cursor") from exc


class ClientBookingService:
    def __init__(self, session: AsyncSession, redis: Redis, cache: SlotCache) -> None:
        self.session = session
        self.redis = redis
        self.cache = cache
        self.holds = HoldStore(redis)
        self.repo = BookingRepository(session)
        self.reads = BookingReadRepository(session)
        self.barbers = BarberRepository(session)
        self.branches = BranchService(session)
        self.availability = AvailabilityService(session, cache)
        self.audit = AuditService(session)
        self.events = BookingEvents(session)
        self._viewer: uuid.UUID | None = None  # client whose own holds don't count as busy

    async def _rate(self, key: str, limit: tuple[int, int]) -> None:
        try:
            limited = await hit_rate_limit(self.redis, key, limit[0], limit[1])
        except RedisError:
            return  # never block bookings because the limiter is down
        if limited:
            raise RateLimitedError(headers={"Retry-After": str(limit[1])})

    # ------------------------------------------------------------------ holds

    async def place_hold(
        self,
        branch_id: uuid.UUID,
        client: Client,
        *,
        barber_id: uuid.UUID | None,
        service_ids: Sequence[uuid.UUID],
        start_at: datetime,
        now: datetime,
        reschedule_booking_id: uuid.UUID | None = None,
    ) -> PlacedHold:
        self._viewer = client.id
        await self._rate(f"hold:{client.id}", HOLD_RATE)
        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        start_at = start_at.astimezone(UTC)
        day = start_at.astimezone(tz).date()

        exclude: list[uuid.UUID] = []
        if reschedule_booking_id is not None:
            existing = await self.repo.get_for_client(client.id, reschedule_booking_id)
            if existing is None:
                raise NotFoundError("Booking not found")
            exclude.append(existing.id)

        bounds = local_day_bounds(day, tz)
        barber_scope = await self.barbers.list_page(
            branch_id, only_active=True, only_bookable=True, limit=1000
        )
        others = await self.holds.busy_for(
            [b.id for b in barber_scope[0]], bounds.start, bounds.end, now, client.id
        )
        result = await self.availability.compute(
            branch_id,
            service_ids=service_ids,
            barber_id=barber_id,
            date_from=day,
            date_to=day,
            now=now,
            audience=Audience.CLIENT,
            extra_busy=others,
            exclude_booking_ids=exclude,
        )
        free = dict(result.days[0].sorted_items()) if result.days else {}
        candidates = list(free.get(start_at, []))
        if not candidates:
            raise await self._conflict(branch_id, service_ids, barber_id, start_at, day, now)

        ordered = candidates
        if barber_id is None and len(candidates) > 1:
            ordered = await self._by_load(candidates, bounds.start, bounds.end, barber_scope[0])
        for candidate in ordered:
            duration = result.durations[candidate]
            hold = Hold(
                id=HoldStore.new_id(),
                client_id=client.id,
                barber_id=candidate,
                service_ids=tuple(dict.fromkeys(service_ids)),
                start_at=start_at,
                end_at=start_at + timedelta(minutes=duration),
                blocked_until=start_at + timedelta(minutes=duration + salon.buffer_min),
                expires_at=now + HOLD_TTL,
            )
            try:
                placed = await self.holds.place(hold, now)
            except HoldUnavailableError as exc:
                raise HoldsUnavailableError() from exc
            if placed:
                barber = next(b for b in barber_scope[0] if b.id == candidate)
                quote = await quote_for(self.session, branch_id, candidate, service_ids, client)
                return PlacedHold(hold=hold, barber=barber, quote=quote)
        raise await self._conflict(branch_id, service_ids, barber_id, start_at, day, now)

    async def _by_load(
        self,
        candidates: Sequence[uuid.UUID],
        day_start: datetime,
        day_end: datetime,
        barbers: Sequence[Barber],
    ) -> list[uuid.UUID]:
        rows = await self.reads.active_between(candidates, day_start, day_end)
        minutes: dict[uuid.UUID, int] = {}
        counts: dict[uuid.UUID, int] = {}
        for row in rows:
            if row.kind is BookingKind.APPOINTMENT:
                span = int((row.end_at - row.start_at).total_seconds() // 60)
                minutes[row.barber_id] = minutes.get(row.barber_id, 0) + span
                counts[row.barber_id] = counts.get(row.barber_id, 0) + 1
        order = {b.id: b.sort_order for b in barbers}
        remaining = list(candidates)
        ranked: list[uuid.UUID] = []
        while remaining:
            best = pick_least_loaded(remaining, minutes, counts, order)
            ranked.append(best)
            remaining.remove(best)
        return ranked

    async def _conflict(
        self,
        branch_id: uuid.UUID,
        service_ids: Sequence[uuid.UUID],
        barber_id: uuid.UUID | None,
        start_at: datetime,
        day: date,
        now: datetime,
    ) -> SlotConflictError:
        """409 with the nearest alternatives, hiding times held by other clients."""
        salon = await self.branches.settings(branch_id)
        bounds = local_day_bounds(day, ZoneInfo(salon.timezone))
        scope, _ = await self.barbers.list_page(
            branch_id, only_active=True, only_bookable=True, limit=1000
        )
        held = await self.holds.busy_for(
            [b.id for b in scope], bounds.start, bounds.end, now, self._viewer
        )
        slots = await alternatives(
            self.availability,
            branch_id,
            service_ids=service_ids,
            barber_id=barber_id,
            around=start_at,
            day=day,
            now=now,
            extra_busy=held,
        )
        return SlotConflictError(
            details={"alternatives": [slot.model_dump(mode="json") for slot in slots]}
        )

    async def release_hold(self, client: Client, hold_id: str) -> None:
        try:
            hold = await self.holds.get(hold_id)
        except HoldUnavailableError:
            return
        if hold is not None and hold.client_id == client.id:
            await self.holds.release(hold)

    async def _own_hold(self, client: Client, hold_id: str, now: datetime) -> Hold:
        try:
            hold = await self.holds.get(hold_id)
        except HoldUnavailableError as exc:
            raise HoldsUnavailableError() from exc
        if hold is None or hold.client_id != client.id or hold.expires_at <= now:
            raise ConflictError(
                "The reserved time has expired, choose a time again", code="hold_expired"
            )
        return hold

    # ------------------------------------------------------------------ create

    async def _idempotency_guard(self, client: Client, key: str, fingerprint: str) -> None:
        redis_key = f"idem:{client.id}:{key}"
        try:
            stored = await self.redis.set(redis_key, fingerprint, nx=True, ex=IDEMPOTENCY_TTL)
            if not stored:
                previous = await self.redis.get(redis_key)
                if previous is not None and str(previous) != fingerprint:
                    raise ValidationAppError(
                        "Idempotency-Key was already used with a different request",
                        code="idempotency_mismatch",
                    )
        except RedisError:
            return  # the unique index still protects against duplicates

    async def create(
        self,
        branch_id: uuid.UUID,
        client: Client,
        actor: Actor,
        *,
        hold_id: str,
        comment: str | None,
        bonus_to_spend: int,
        idempotency_key: str,
        now: datetime,
        promo_code: str | None = None,
        status: BookingStatus = BookingStatus.CONFIRMED,
        source: BookingSource = BookingSource.MINIAPP,
        notify_client: bool = True,
    ) -> CreatedBooking:
        if not idempotency_key or len(idempotency_key) > 64:
            raise ValidationAppError(
                "Idempotency-Key header is required (≤ 64 chars)", code="idempotency_key_required"
            )
        client_id = client.id  # objects are expired after a rollback; keep plain values
        self._viewer = client_id
        fingerprint = hashlib.sha256(
            f"{hold_id}|{comment}|{bonus_to_spend}|{promo_code or ''}".encode()
        ).hexdigest()
        await self._idempotency_guard(client, idempotency_key, fingerprint)
        existing = await self.repo.get_by_idempotency_key(client.id, idempotency_key)
        if existing is not None:
            return CreatedBooking(existing, created=False)

        await self._rate(f"booking:m:{client.id}", BOOKING_RATE_MINUTE)
        await self._rate(f"booking:d:{client.id}", BOOKING_RATE_DAY)

        if not client.phone:
            raise ValidationAppError("Share your phone number first", code="phone_required")
        salon = await self.branches.settings(branch_id)
        if await self.repo.count_active_upcoming(client.id, now) >= (
            salon.max_active_bookings_per_client
        ):
            raise ConflictError(
                "Too many upcoming bookings",
                code="too_many_bookings",
                details={"limit": salon.max_active_bookings_per_client},
            )

        tz = ZoneInfo(salon.timezone)
        hold = await self._own_hold(client, hold_id, now)
        await self._ensure_still_free(branch_id, salon, hold, client, now, exclude=())

        quote = await quote_for(self.session, branch_id, hold.barber_id, hold.service_ids, client)
        promo = None
        if promo_code:
            promo, discount = await PromoService(self.session).resolve(
                promo_code, client, salon, quote.subtotal, now, lock=True
            )
            quote = await quote_for(
                self.session, branch_id, hold.barber_id, hold.service_ids, client, discount
            )
        if bonus_to_spend > quote.max_bonus_spend:
            raise ValidationAppError(
                "Too many bonuses for this booking",
                code="bonus_limit",
                details={"max_bonus_spend": quote.max_bonus_spend},
            )

        booking = Booking(
            branch_id=branch_id,
            client_id=client.id,
            barber_id=hold.barber_id,
            kind=BookingKind.APPOINTMENT,
            status=status,  # Mini App: the slot was free → confirmed immediately
            source=source,
            subtotal=quote.subtotal,
            bonus_spent=bonus_to_spend,
            discount=quote.discount,
            promo_code_id=promo.id if promo else None,
            total_due=quote.total_due(bonus_to_spend),
            comment=comment,
            idempotency_key=idempotency_key,
            services=snapshot_services(quote),
        )
        set_times(booking, hold.start_at, quote.duration_min, salon.buffer_min)
        self.repo.add(booking)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if is_constraint_violation(exc, IDEMPOTENCY_INDEX):
                replay = await self.repo.get_by_idempotency_key(client_id, idempotency_key)
                if replay is not None:
                    return CreatedBooking(replay, created=False)
            if is_constraint_violation(exc, EXCLUSION_CONSTRAINT):
                await self.holds.release(hold)
                await self.cache.bump([hold.barber_id])
                day = hold.start_at.astimezone(tz).date()
                raise await self._conflict(
                    branch_id, hold.service_ids, hold.barber_id, hold.start_at, day, now
                ) from exc
            raise

        if bonus_to_spend > 0:
            await BonusService(self.session).spend_for_booking(booking, bonus_to_spend, now)
        self.audit.record(actor, "booking.create", "booking", booking.id, after=snapshot(booking))
        notification = await self.events.emit(
            NotificationType.BOOKING_CREATED, booking, salon, notify_client=notify_client
        )
        await self.session.commit()

        await self.holds.release(hold)
        await self.cache.bump([booking.barber_id])
        await publish(self.redis, notification)
        return CreatedBooking(booking, created=True)

    async def check_promo(
        self, branch_id: uuid.UUID, client: Client, hold_id: str, code: str, now: datetime
    ) -> tuple[Quote, str]:
        """The hold's quote with the code applied (nothing is reserved until booking)."""
        hold = await self._own_hold(client, hold_id, now)
        salon = await self.branches.settings(branch_id)
        base = await quote_for(self.session, branch_id, hold.barber_id, hold.service_ids, client)
        promo, discount = await PromoService(self.session).resolve(
            code, client, salon, base.subtotal, now
        )
        quote = await quote_for(
            self.session, branch_id, hold.barber_id, hold.service_ids, client, discount
        )
        return quote, promo.code

    async def _ensure_still_free(
        self,
        branch_id: uuid.UUID,
        salon: SalonSettings,
        hold: Hold,
        client: Client,
        now: datetime,
        exclude: Sequence[uuid.UUID],
    ) -> None:
        """The schedule or settings may have changed since the hold was placed."""
        tz = ZoneInfo(salon.timezone)
        day = hold.start_at.astimezone(tz).date()
        result = await self.availability.compute(
            branch_id,
            service_ids=hold.service_ids,
            barber_id=hold.barber_id,
            date_from=day,
            date_to=day,
            now=now,
            audience=Audience.CLIENT,
            exclude_booking_ids=exclude,
        )
        free = dict(result.days[0].sorted_items()) if result.days else {}
        if hold.barber_id not in free.get(hold.start_at, []):
            await self.holds.release(hold)
            raise await self._conflict(
                branch_id, hold.service_ids, hold.barber_id, hold.start_at, day, now
            )

    # ------------------------------------------------------------------ manage

    async def get(self, client: Client, booking_id: uuid.UUID) -> Booking:
        booking = await self.repo.get_for_client(client.id, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found")
        return booking

    async def cancel(
        self,
        branch_id: uuid.UUID,
        client: Client,
        actor: Actor,
        booking_id: uuid.UUID,
        reason: str | None,
        now: datetime,
    ) -> Booking:
        booking = await self.get(client, booking_id)
        salon = await self.branches.settings(branch_id)
        if booking.status not in ACTIVE_BOOKING_STATUSES:
            raise ConflictError("Booking is not active", code="booking_not_active")
        if not can_change(booking, now, salon.cancel_min_hours):
            raise ValidationAppError(
                "It is too late to cancel online, please call the salon",
                code="cancel_too_late",
                details={"min_hours": salon.cancel_min_hours},
            )
        before = {"status": booking.status.value}
        booking.status = BookingStatus.CANCELLED
        booking.cancelled_by = ActorType.CLIENT
        booking.cancelled_at = now
        booking.cancel_reason = reason
        await self.session.flush()
        await BonusService(self.session).refund_for_booking(booking, now)
        self.audit.record(
            actor,
            "booking.cancel",
            "booking",
            booking.id,
            before=before,
            after={"status": booking.status.value, "reason": reason},
        )
        notification = await self.events.emit(
            NotificationType.BOOKING_CANCELLED,
            booking,
            salon,
            cancelled_by=ActorType.CLIENT.value,
            reason=reason,
        )
        await self.session.commit()
        await self.cache.bump([booking.barber_id])
        await publish(self.redis, notification)
        return booking

    async def reschedule(
        self,
        branch_id: uuid.UUID,
        client: Client,
        actor: Actor,
        booking_id: uuid.UUID,
        hold_id: str,
        now: datetime,
    ) -> Booking:
        self._viewer = client.id
        booking = await self.get(client, booking_id)
        salon = await self.branches.settings(branch_id)
        if booking.status not in ACTIVE_BOOKING_STATUSES:
            raise ConflictError("Booking is not active", code="booking_not_active")
        if not can_change(booking, now, salon.reschedule_min_hours):
            raise ValidationAppError(
                "It is too late to reschedule online, please call the salon",
                code="reschedule_too_late",
                details={"min_hours": salon.reschedule_min_hours},
            )
        tz = ZoneInfo(salon.timezone)
        hold = await self._own_hold(client, hold_id, now)
        current_services = {line.service_id for line in booking.services}
        if set(hold.service_ids) != current_services:
            raise ValidationAppError(
                "The hold is for different services", code="hold_services_mismatch"
            )
        await self._ensure_still_free(branch_id, salon, hold, client, now, exclude=[booking.id])

        old_barber, old_start = booking.barber_id, booking.start_at
        before = snapshot(booking)
        if hold.barber_id != booking.barber_id:
            quote = await quote_for(
                self.session, branch_id, hold.barber_id, hold.service_ids, client
            )
            booking.services.clear()
            await self.session.flush()
            booking.services.extend(snapshot_services(quote))
            booking.subtotal = quote.subtotal
            await cap_bonus(self.session, booking, now)
            duration = quote.duration_min
        else:
            duration = sum(line.duration_min for line in booking.services)
        booking.barber_id = hold.barber_id
        set_times(booking, hold.start_at, duration, salon.buffer_min)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if is_constraint_violation(exc, EXCLUSION_CONSTRAINT):
                await self.holds.release(hold)
                day = hold.start_at.astimezone(tz).date()
                raise await self._conflict(
                    branch_id, hold.service_ids, hold.barber_id, hold.start_at, day, now
                ) from exc
            raise
        await self.session.execute(
            delete(BookingReminder).where(BookingReminder.booking_id == booking.id)
        )
        self.audit.record(
            actor,
            "booking.reschedule",
            "booking",
            booking.id,
            before={"start_at": before["start_at"], "barber_id": before["barber_id"]},
            after={"start_at": booking.start_at.isoformat(), "barber_id": str(booking.barber_id)},
        )
        notification = await self.events.emit(
            NotificationType.BOOKING_RESCHEDULED, booking, salon, old_start_at=old_start
        )
        await self.session.commit()
        await self.holds.release(hold)
        await self.cache.bump({old_barber, booking.barber_id})
        await publish(self.redis, notification)
        return booking

    async def list(
        self, client: Client, *, upcoming: bool, now: datetime, limit: int, cursor: str | None
    ) -> tuple[list[Booking], str | None]:
        items = await self.repo.list_for_client(
            client.id, upcoming=upcoming, now=now, limit=limit + 1, after=decode_cursor(cursor)
        )
        has_more = len(items) > limit
        items = items[:limit]
        return items, encode_cursor(items[-1]) if has_more and items else None

    async def last_visit(self, client: Client, now: datetime) -> Booking | None:
        return await self.repo.last_visit(client.id, now)
