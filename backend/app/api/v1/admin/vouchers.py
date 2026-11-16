"""Gift certificates, subscription plans, sold subscriptions and applying them to bookings."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminContext, NowDep, SessionDep, require
from app.core.errors import ErrorResponse
from app.models import Client, ClientSubscription, GiftCertificate, SubscriptionPlan, VoucherUse
from app.schemas.vouchers import (
    ApplyCertificateIn,
    ApplySubscriptionIn,
    CertificateIn,
    CertificateOut,
    PlanIn,
    PlanOut,
    SubscriptionOut,
    SubscriptionSellIn,
    VoucherUseOut,
)
from app.services.audit import AuditService
from app.services.branches import BranchService
from app.services.permissions import Perm
from app.services.vouchers import VoucherService, certificate_state, subscription_state

router = APIRouter(tags=["admin-vouchers"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.CLIENTS_READ))]
CanSell = Annotated[AdminContext, Depends(require(Perm.CLIENTS_WRITE))]
CanPlans = Annotated[AdminContext, Depends(require(Perm.SETTINGS_WRITE))]
CanBookings = Annotated[AdminContext, Depends(require(Perm.BOOKINGS_WRITE))]


async def _today(session: SessionDep, ctx: AdminContext, now: NowDep) -> date:
    salon = await BranchService(session).settings(ctx.branch_id)
    return now.astimezone(ZoneInfo(salon.timezone)).date()


def cert_out(cert: GiftCertificate, today: date) -> CertificateOut:
    return CertificateOut(
        id=cert.id,
        code=cert.code,
        amount=cert.amount,
        balance=cert.balance,
        state=certificate_state(cert, today),
        buyer_name=cert.buyer_name,
        recipient_name=cert.recipient_name,
        note=cert.note,
        expires_on=cert.expires_on,
        payment_method=cert.payment_method,
        sold_at=cert.sold_at,
    )


def sub_out(sub: ClientSubscription, client_name: str, today: date) -> SubscriptionOut:
    return SubscriptionOut(
        id=sub.id,
        client_id=sub.client_id,
        client_name=client_name,
        name=sub.name,
        service_ids=list(sub.service_ids or []),
        visits_total=sub.visits_total,
        visits_left=sub.visits_left,
        price=sub.price,
        expires_on=sub.expires_on,
        state=subscription_state(sub, today),
        sold_at=sub.sold_at,
    )


def plan_out(plan: SubscriptionPlan) -> PlanOut:
    return PlanOut(
        id=plan.id,
        name=plan.name,
        service_ids=list(plan.service_ids or []),
        visits=plan.visits,
        price=plan.price,
        valid_days=plan.valid_days,
        is_active=plan.is_active,
    )


# ---- certificates -------------------------------------------------------------------------


@router.get("/certificates", response_model=list[CertificateOut], responses=ERRORS)
async def list_certificates(
    ctx: CanRead,
    session: SessionDep,
    now: NowDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CertificateOut]:
    today = await _today(session, ctx, now)
    rows = await VoucherService(session).certificates(ctx.branch_id, limit)
    return [cert_out(row, today) for row in rows]


@router.get("/certificates/lookup", response_model=CertificateOut, responses=ERRORS)
async def lookup_certificate(
    code: str, ctx: CanRead, session: SessionDep, now: NowDep
) -> CertificateOut:
    cert = await VoucherService(session).find_certificate(ctx.branch_id, code)
    return cert_out(cert, await _today(session, ctx, now))


@router.post(
    "/certificates",
    response_model=CertificateOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def sell_certificate(
    body: CertificateIn, ctx: CanSell, session: SessionDep, now: NowDep
) -> CertificateOut:
    """Sell a gift certificate; the code is generated (GIFT-XXXX-XXXX)."""
    cert = await VoucherService(session).sell_certificate(
        ctx.branch_id,
        amount=body.amount,
        expires_on=body.expires_on,
        buyer_name=body.buyer_name,
        recipient_name=body.recipient_name,
        note=body.note,
        payment_method=body.payment_method,
        actor=ctx.actor,
    )
    return cert_out(cert, await _today(session, ctx, now))


@router.post("/certificates/{cert_id}/cancel", response_model=CertificateOut, responses=ERRORS)
async def cancel_certificate(
    cert_id: uuid.UUID, ctx: CanSell, session: SessionDep, now: NowDep
) -> CertificateOut:
    cert = await VoucherService(session).cancel_certificate(ctx.branch_id, cert_id, ctx.actor, now)
    return cert_out(cert, await _today(session, ctx, now))


# ---- subscription plans -------------------------------------------------------------------


@router.get("/subscription-plans", response_model=list[PlanOut], responses=ERRORS)
async def list_plans(ctx: CanRead, session: SessionDep) -> list[PlanOut]:
    return [plan_out(plan) for plan in await VoucherService(session).plans(ctx.branch_id)]


@router.post(
    "/subscription-plans",
    response_model=PlanOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_plan(body: PlanIn, ctx: CanPlans, session: SessionDep) -> PlanOut:
    plan = SubscriptionPlan(branch_id=ctx.branch_id, **body.model_dump())
    session.add(plan)
    await session.flush()
    AuditService(session).record(
        ctx.actor, "plan.create", "plan", plan.id, after=body.model_dump(mode="json")
    )
    await session.commit()
    return plan_out(plan)


@router.put("/subscription-plans/{plan_id}", response_model=PlanOut, responses=ERRORS)
async def update_plan(
    plan_id: uuid.UUID, body: PlanIn, ctx: CanPlans, session: SessionDep
) -> PlanOut:
    """Changes apply to future sales only: sold subscriptions keep their snapshot."""
    plan = await VoucherService(session).plan(ctx.branch_id, plan_id)
    for key, value in body.model_dump().items():
        setattr(plan, key, value)
    AuditService(session).record(
        ctx.actor, "plan.update", "plan", plan.id, after=body.model_dump(mode="json")
    )
    await session.commit()
    return plan_out(plan)


# ---- sold subscriptions -------------------------------------------------------------------


async def _client_name(session: SessionDep, sub: ClientSubscription) -> str:
    client = await session.get(Client, sub.client_id)
    return client.name if client else ""


@router.get("/subscriptions", response_model=list[SubscriptionOut], responses=ERRORS)
async def list_subscriptions(
    ctx: CanRead,
    session: SessionDep,
    now: NowDep,
    client_id: uuid.UUID | None = None,
) -> list[SubscriptionOut]:
    today = await _today(session, ctx, now)
    rows = await VoucherService(session).client_subscriptions(ctx.branch_id, client_id)
    return [sub_out(sub, name, today) for sub, name in rows]


@router.post(
    "/subscriptions",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def sell_subscription(
    body: SubscriptionSellIn, ctx: CanSell, session: SessionDep, now: NowDep
) -> SubscriptionOut:
    today = await _today(session, ctx, now)
    service = VoucherService(session)
    sub = await service.sell_subscription(
        ctx.branch_id,
        client_id=body.client_id,
        plan_id=body.plan_id,
        payment_method=body.payment_method,
        actor=ctx.actor,
        today=today,
    )
    ((_, name),) = [
        row
        for row in await service.client_subscriptions(ctx.branch_id, sub.client_id)
        if row[0].id == sub.id
    ]
    return sub_out(sub, name, today)


@router.post("/subscriptions/{sub_id}/cancel", response_model=SubscriptionOut, responses=ERRORS)
async def cancel_subscription(
    sub_id: uuid.UUID, ctx: CanSell, session: SessionDep, now: NowDep
) -> SubscriptionOut:
    service = VoucherService(session)
    sub = await service.cancel_subscription(ctx.branch_id, sub_id, ctx.actor, now)
    ((_, name),) = [
        row
        for row in await service.client_subscriptions(ctx.branch_id, sub.client_id)
        if row[0].id == sub.id
    ]
    return sub_out(sub, name, await _today(session, ctx, now))


# ---- applying to a booking ----------------------------------------------------------------


async def _uses_out(session: SessionDep, uses: list[VoucherUse]) -> list[VoucherUseOut]:
    result = []
    for use in uses:
        if use.certificate_id is not None:
            cert = await session.get(GiftCertificate, use.certificate_id)
            kind, label = "certificate", cert.code if cert else ""
        else:
            sub = await session.get(ClientSubscription, use.subscription_id)
            kind, label = "subscription", sub.name if sub else ""
        result.append(
            VoucherUseOut(
                id=use.id,
                kind=kind,
                label=label,
                amount=use.amount,
                created_at=use.created_at,
            )
        )
    return result


@router.get("/bookings/{booking_id}/vouchers", response_model=list[VoucherUseOut], responses=ERRORS)
async def booking_vouchers(
    booking_id: uuid.UUID, ctx: CanBookings, session: SessionDep
) -> list[VoucherUseOut]:
    return await _uses_out(session, await VoucherService(session).uses(ctx.branch_id, booking_id))


@router.post(
    "/bookings/{booking_id}/vouchers/certificate",
    response_model=list[VoucherUseOut],
    responses=ERRORS,
)
async def apply_certificate(
    booking_id: uuid.UUID,
    body: ApplyCertificateIn,
    ctx: CanBookings,
    session: SessionDep,
    now: NowDep,
) -> list[VoucherUseOut]:
    service = VoucherService(session)
    await service.apply_certificate(
        ctx.branch_id,
        booking_id,
        code=body.code,
        amount=body.amount,
        actor=ctx.actor,
        today=await _today(session, ctx, now),
    )
    return await _uses_out(session, await service.uses(ctx.branch_id, booking_id))


@router.post(
    "/bookings/{booking_id}/vouchers/subscription",
    response_model=list[VoucherUseOut],
    responses=ERRORS,
)
async def apply_subscription(
    booking_id: uuid.UUID,
    body: ApplySubscriptionIn,
    ctx: CanBookings,
    session: SessionDep,
    now: NowDep,
) -> list[VoucherUseOut]:
    service = VoucherService(session)
    await service.apply_subscription(
        ctx.branch_id,
        booking_id,
        subscription_id=body.subscription_id,
        actor=ctx.actor,
        today=await _today(session, ctx, now),
    )
    return await _uses_out(session, await service.uses(ctx.branch_id, booking_id))


@router.delete("/vouchers/{use_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def undo_voucher(use_id: uuid.UUID, ctx: CanBookings, session: SessionDep) -> None:
    await VoucherService(session).undo(ctx.branch_id, use_id, ctx.actor)
