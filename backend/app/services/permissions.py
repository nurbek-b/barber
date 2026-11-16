"""Role → permission mapping. The UI receives the list via /admin/auth/me."""

from __future__ import annotations

from enum import StrEnum

from app.models.enums import AdminRole


class Perm(StrEnum):
    DASHBOARD_READ = "dashboard:read"
    BARBERS_READ = "barbers:read"
    BARBERS_READ_OWN = "barbers:read_own"
    BARBERS_WRITE = "barbers:write"
    SERVICES_READ = "services:read"
    SERVICES_WRITE = "services:write"
    CLIENTS_READ = "clients:read"
    CLIENTS_WRITE = "clients:write"
    BOOKINGS_READ = "bookings:read"
    BOOKINGS_READ_OWN = "bookings:read_own"
    BOOKINGS_WRITE = "bookings:write"
    BOOKINGS_STATUS_OWN = "bookings:status_own"
    FINANCE_READ = "finance:read"
    FINANCE_EXPORT = "finance:export"
    PAYOUTS_WRITE = "payouts:write"
    SETTINGS_READ = "settings:read"
    SETTINGS_WRITE = "settings:write"
    BONUS_ADJUST = "bonus:adjust"
    BONUS_SETTINGS_WRITE = "bonus_settings:write"
    STAFF_MANAGE = "staff:manage"
    AUDIT_READ = "audit:read"
    NOTIFICATIONS_READ = "notifications:read"


_OWNER_ONLY = frozenset(
    {Perm.BONUS_SETTINGS_WRITE, Perm.STAFF_MANAGE, Perm.AUDIT_READ, Perm.PAYOUTS_WRITE}
)
_OWN_SCOPED = frozenset({Perm.BARBERS_READ_OWN, Perm.BOOKINGS_READ_OWN, Perm.BOOKINGS_STATUS_OWN})

ROLE_PERMISSIONS: dict[AdminRole, frozenset[Perm]] = {
    AdminRole.OWNER: frozenset(Perm) - _OWN_SCOPED,
    AdminRole.ADMIN: frozenset(Perm) - _OWN_SCOPED - _OWNER_ONLY,
    AdminRole.BARBER: frozenset(
        {
            Perm.BARBERS_READ_OWN,
            Perm.BOOKINGS_READ_OWN,
            Perm.BOOKINGS_STATUS_OWN,
            Perm.SERVICES_READ,
            Perm.NOTIFICATIONS_READ,
        }
    ),
}


def permissions_for(role: AdminRole) -> frozenset[Perm]:
    return ROLE_PERMISSIONS[role]


def has_permission(role: AdminRole, perm: Perm) -> bool:
    return perm in ROLE_PERMISSIONS[role]
