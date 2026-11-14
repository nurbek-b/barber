from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    RU = "ru"
    KY = "ky"
    EN = "en"


class AdminRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    BARBER = "barber"


class BookingKind(StrEnum):
    APPOINTMENT = "appointment"
    BLOCK = "block"


class BookingStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


ACTIVE_BOOKING_STATUSES = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


class BookingSource(StrEnum):
    MINIAPP = "miniapp"
    ADMIN = "admin"
    BOT = "bot"


class PaymentMethod(StrEnum):
    CASH = "cash"
    CARD = "card"
    TRANSFER = "transfer"
    MIXED = "mixed"


class ActorType(StrEnum):
    ADMIN = "admin"
    CLIENT = "client"
    SYSTEM = "system"


class ScheduleExceptionKind(StrEnum):
    DAY_OFF = "day_off"
    VACATION = "vacation"
    CUSTOM_HOURS = "custom_hours"


class BonusTxType(StrEnum):
    EARN = "earn"
    SPEND = "spend"
    EXPIRE = "expire"
    REFUND = "refund"
    MANUAL = "manual"
    REFERRAL = "referral"
    WELCOME = "welcome"
    BIRTHDAY = "birthday"


class LevelRule(StrEnum):
    ANY = "any"  # reach either threshold
    ALL = "all"  # reach both thresholds


class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"


class NotificationType(StrEnum):
    BOOKING_CREATED = "booking_created"
    BOOKING_CANCELLED = "booking_cancelled"
    BOOKING_RESCHEDULED = "booking_rescheduled"
    BOOKING_STATUS_CHANGED = "booking_status_changed"
    CLIENT_REGISTERED = "client_registered"
