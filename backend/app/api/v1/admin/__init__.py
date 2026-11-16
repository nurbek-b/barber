from fastapi import APIRouter

from app.api.v1.admin import (
    auth,
    availability,
    barbers,
    bonus,
    bookings,
    broadcasts,
    clients,
    notifications,
    promo,
    reports,
    reviews,
    schedule,
    services,
    settings,
    staff,
    ws,
)

router = APIRouter(prefix="/admin")
router.include_router(auth.router)
router.include_router(barbers.router)
router.include_router(schedule.router)
router.include_router(services.router)
router.include_router(availability.router)
router.include_router(bookings.router)
router.include_router(notifications.router)
router.include_router(reviews.router)
router.include_router(promo.router)
router.include_router(broadcasts.router)
router.include_router(bonus.router)
router.include_router(clients.router)
router.include_router(settings.router)
router.include_router(staff.router)
router.include_router(reports.router)
router.include_router(ws.router)
