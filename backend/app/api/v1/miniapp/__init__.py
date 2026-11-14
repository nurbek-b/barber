from fastapi import APIRouter

from app.api.v1.miniapp import availability, bonus, bookings, catalog, me

router = APIRouter(prefix="/miniapp")
router.include_router(me.router)
router.include_router(catalog.router)
router.include_router(availability.router)
router.include_router(bookings.router)
router.include_router(bonus.router)
