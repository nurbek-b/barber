from fastapi import APIRouter

from app.api.v1 import admin, health, miniapp, public

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(miniapp.router)
router.include_router(admin.router)
router.include_router(public.router)
