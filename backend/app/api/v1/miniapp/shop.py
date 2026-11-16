from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Response, status

from app.api.deps import MiniappDep, NowDep, SessionDep
from app.api.v1.shop_views import order_out, product_out
from app.core.errors import ErrorResponse
from app.schemas.shop import OrderIn, OrderOut, OrderPaymentOut, ProductOut
from app.services.shop import OrderPaymentInfo, ShopService

router = APIRouter(tags=["miniapp-shop"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def payment_out(info: OrderPaymentInfo) -> OrderPaymentOut:
    return OrderPaymentOut(
        order_id=info.order.id,
        status=info.order.status,
        qr_url=info.qr_url,
        note=info.note,
        currency=info.currency,
        total=info.order.total,
        amount_left=info.amount_left,
    )


@router.get("/products", response_model=list[ProductOut], responses=ERRORS)
async def products(ctx: MiniappDep, session: SessionDep) -> list[ProductOut]:
    rows = await ShopService(session).products(ctx.branch_id, only_active=True)
    return [product_out(row) for row in rows if row.stock is None or row.stock > 0]


@router.post("/orders", response_model=OrderOut, status_code=201, responses=ERRORS)
async def place_order(
    body: OrderIn,
    response: Response,
    ctx: MiniappDep,
    session: SessionDep,
    now: NowDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", max_length=64)],
) -> OrderOut:
    """Place an order (pickup at the salon); pay it by the salon QR afterwards."""
    order, created = await ShopService(session).place(
        ctx.branch_id,
        ctx.identity.client,
        [(line.product_id, line.quantity) for line in body.items],
        body.comment,
        idempotency_key,
        ctx.actor,
        now,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return order_out(order)


@router.get("/orders", response_model=list[OrderOut], responses=ERRORS)
async def my_orders(ctx: MiniappDep, session: SessionDep) -> list[OrderOut]:
    return [order_out(o) for o in await ShopService(session).client_orders(ctx.identity.client)]


@router.get("/orders/{order_id}/payment", response_model=OrderPaymentOut, responses=ERRORS)
async def order_payment(
    order_id: uuid.UUID, ctx: MiniappDep, session: SessionDep
) -> OrderPaymentOut:
    return payment_out(await ShopService(session).payment_info(ctx.identity.client, order_id))


@router.post("/orders/{order_id}/payment", response_model=OrderPaymentOut, responses=ERRORS)
async def claim_order_payment(
    order_id: uuid.UUID, ctx: MiniappDep, session: SessionDep, now: NowDep
) -> OrderPaymentOut:
    """'I paid': the salon is alerted and confirms after checking its bank app."""
    return payment_out(await ShopService(session).claim(ctx.identity.client, order_id, now))


@router.post("/orders/{order_id}/cancel", response_model=OrderOut, responses=ERRORS)
async def cancel_order(order_id: uuid.UUID, ctx: MiniappDep, session: SessionDep) -> OrderOut:
    return order_out(await ShopService(session).cancel_by_client(ctx.identity.client, order_id))
