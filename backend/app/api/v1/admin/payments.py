"""Booking payments (QR transfers, deposits) and the bank QR images clients pay by."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.deps import AdminContext, NowDep, SessionDep, SettingsDep, require
from app.api.v1.admin.barbers import to_out as barber_out
from app.api.v1.admin.settings import to_out as salon_out
from app.core.errors import ErrorResponse
from app.models import Payment
from app.schemas.admin import SalonSettingsOut
from app.schemas.bookings import AdminPaymentIn, PaymentDecisionIn, PaymentOut
from app.schemas.catalog import BarberOut
from app.services.barbers import BarbersService
from app.services.branches import BranchService
from app.services.branding import BrandingService
from app.services.payments import PaymentService
from app.services.permissions import Perm

router = APIRouter(tags=["admin-payments"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanBookings = Annotated[AdminContext, Depends(require(Perm.BOOKINGS_WRITE))]
CanBarbers = Annotated[AdminContext, Depends(require(Perm.BARBERS_WRITE))]
CanSettings = Annotated[AdminContext, Depends(require(Perm.SETTINGS_WRITE))]
Image = Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 5 MB")]


def payment_out(payment: Payment) -> PaymentOut:
    return PaymentOut.model_validate(payment, from_attributes=True)


@router.get("/bookings/{booking_id}/payments", response_model=list[PaymentOut], responses=ERRORS)
async def list_payments(
    booking_id: uuid.UUID, ctx: CanBookings, session: SessionDep
) -> list[PaymentOut]:
    rows = await PaymentService(session).list_for_booking(ctx.branch_id, booking_id)
    return [payment_out(row) for row in rows]


@router.post(
    "/bookings/{booking_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def add_payment(
    booking_id: uuid.UUID, body: AdminPaymentIn, ctx: CanBookings, session: SessionDep, now: NowDep
) -> PaymentOut:
    """Money the salon received itself (cash deposit, a transfer it saw). Counts at once."""
    payment = await PaymentService(session).add(
        ctx.branch_id,
        booking_id,
        amount=body.amount,
        method=body.method,
        note=body.note,
        actor=ctx.actor,
        now=now,
    )
    return payment_out(payment)


@router.post("/payments/{payment_id}/confirm", response_model=PaymentOut, responses=ERRORS)
async def confirm_payment(
    payment_id: uuid.UUID,
    body: PaymentDecisionIn,
    ctx: CanBookings,
    session: SessionDep,
    now: NowDep,
) -> PaymentOut:
    """The money arrived (optionally a different amount). A prepaid PENDING booking becomes
    CONFIRMED once the required prepayment is covered."""
    payment = await PaymentService(session).decide(
        ctx.branch_id, payment_id, confirm=True, amount=body.amount, actor=ctx.actor, now=now
    )
    return payment_out(payment)


@router.post("/payments/{payment_id}/reject", response_model=PaymentOut, responses=ERRORS)
async def reject_payment(
    payment_id: uuid.UUID, ctx: CanBookings, session: SessionDep, now: NowDep
) -> PaymentOut:
    payment = await PaymentService(session).decide(
        ctx.branch_id, payment_id, confirm=False, amount=None, actor=ctx.actor, now=now
    )
    return payment_out(payment)


# ---- QR images ----------------------------------------------------------------------------


@router.post("/settings/salon/payment-qr", response_model=SalonSettingsOut, responses=ERRORS)
async def upload_salon_qr(
    file: Image, ctx: CanSettings, session: SessionDep, settings: SettingsDep
) -> SalonSettingsOut:
    content = await file.read(settings.max_upload_bytes + 1)
    await BrandingService(session, settings).set_payment_qr(ctx.branch_id, content, ctx.actor)
    return salon_out(await BranchService(session).settings(ctx.branch_id))


@router.delete("/settings/salon/payment-qr", response_model=SalonSettingsOut, responses=ERRORS)
async def delete_salon_qr(
    ctx: CanSettings, session: SessionDep, settings: SettingsDep
) -> SalonSettingsOut:
    await BrandingService(session, settings).remove_payment_qr(ctx.branch_id, ctx.actor)
    return salon_out(await BranchService(session).settings(ctx.branch_id))


async def _barber_out(
    service: BarbersService, barber_id: uuid.UUID, branch_id: uuid.UUID
) -> BarberOut:
    barber = await service.get(branch_id, barber_id)
    return barber_out(barber, barber.id in await service.scheduled_ids([barber.id]))


@router.post("/barbers/{barber_id}/payment-qr", response_model=BarberOut, responses=ERRORS)
async def upload_barber_qr(
    barber_id: uuid.UUID,
    file: Image,
    ctx: CanBarbers,
    session: SessionDep,
    settings: SettingsDep,
) -> BarberOut:
    """The barber's own bank QR (set by the owner); clients of this barber pay by it."""
    content = await file.read(settings.max_upload_bytes + 1)
    service = BarbersService(session, settings)
    barber = await service.get(ctx.branch_id, barber_id)
    await BrandingService(session, settings).set_payment_qr(
        ctx.branch_id, content, ctx.actor, barber=barber
    )
    return await _barber_out(service, barber_id, ctx.branch_id)


@router.delete("/barbers/{barber_id}/payment-qr", response_model=BarberOut, responses=ERRORS)
async def delete_barber_qr(
    barber_id: uuid.UUID, ctx: CanBarbers, session: SessionDep, settings: SettingsDep
) -> BarberOut:
    service = BarbersService(session, settings)
    barber = await service.get(ctx.branch_id, barber_id)
    await BrandingService(session, settings).remove_payment_qr(
        ctx.branch_id, ctx.actor, barber=barber
    )
    return await _barber_out(service, barber_id, ctx.branch_id)
