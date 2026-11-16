"""Import every model so Base.metadata is complete (Alembic autogenerate, tests)."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.bonus import BonusLotConsumption, BonusSettings, BonusTransaction, LoyaltyLevel
from app.models.booking import Booking, BookingReminder, BookingService
from app.models.branch import Branch, SalonSettings
from app.models.broadcast import Broadcast
from app.models.catalog import (
    Barber,
    BarberSchedule,
    BarberScheduleException,
    BarberService,
    Service,
    ServiceCategory,
)
from app.models.notification import Notification, NotificationRead, TelegramOutbox
from app.models.payment import Payment
from app.models.promo import PromoCode
from app.models.staff import AdminRefreshToken, AdminUser
from app.models.user import Client, User
from app.models.waitlist import WaitlistEntry

__all__ = [
    "AdminRefreshToken",
    "AdminUser",
    "AuditLog",
    "Barber",
    "BarberSchedule",
    "BarberScheduleException",
    "BarberService",
    "Base",
    "BonusLotConsumption",
    "BonusSettings",
    "BonusTransaction",
    "Booking",
    "BookingReminder",
    "BookingService",
    "Branch",
    "Broadcast",
    "Client",
    "LoyaltyLevel",
    "Notification",
    "NotificationRead",
    "Payment",
    "PromoCode",
    "SalonSettings",
    "Service",
    "ServiceCategory",
    "TelegramOutbox",
    "User",
    "WaitlistEntry",
]
