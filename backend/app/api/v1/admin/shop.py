"""Shop: products (with photos and stock) and client orders."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.api.deps import AdminContext, NowDep, SessionDep, SettingsDep, require
from app.api.v1.shop_views import admin_order_out, product_out
from app.core.errors import ErrorResponse
from app.models import Client, Product
from app.models.shop import OrderStatus
from app.schemas.shop import AdminOrderOut, OrderStatusIn, ProductIn, ProductOut
from app.services.audit import AuditService
from app.services.permissions import Perm
from app.services.shop import ShopService

router = APIRouter(tags=["admin-shop"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.BOOKINGS_READ))]
CanOrders = Annotated[AdminContext, Depends(require(Perm.BOOKINGS_WRITE))]
CanProducts = Annotated[AdminContext, Depends(require(Perm.SERVICES_WRITE))]


@router.get("/products", response_model=list[ProductOut], responses=ERRORS)
async def list_products(ctx: CanRead, session: SessionDep) -> list[ProductOut]:
    rows = await ShopService(session).products(ctx.branch_id, only_active=False)
    return [product_out(row) for row in rows]


@router.post("/products", response_model=ProductOut, status_code=201, responses=ERRORS)
async def create_product(body: ProductIn, ctx: CanProducts, session: SessionDep) -> ProductOut:
    product = Product(branch_id=ctx.branch_id, **body.model_dump())
    session.add(product)
    await session.flush()
    AuditService(session).record(
        ctx.actor, "product.create", "product", product.id, after=body.model_dump(mode="json")
    )
    await session.commit()
    return product_out(product)


@router.put("/products/{product_id}", response_model=ProductOut, responses=ERRORS)
async def update_product(
    product_id: uuid.UUID, body: ProductIn, ctx: CanProducts, session: SessionDep
) -> ProductOut:
    product = await ShopService(session).product(ctx.branch_id, product_id)
    for key, value in body.model_dump().items():
        setattr(product, key, value)
    AuditService(session).record(
        ctx.actor, "product.update", "product", product.id, after=body.model_dump(mode="json")
    )
    await session.commit()
    return product_out(product)


@router.post("/products/{product_id}/photo", response_model=ProductOut, responses=ERRORS)
async def upload_product_photo(
    product_id: uuid.UUID,
    ctx: CanProducts,
    session: SessionDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, up to 5 MB")],
) -> ProductOut:
    content = await file.read(settings.max_upload_bytes + 1)
    product = await ShopService(session, settings).set_photo(
        ctx.branch_id, product_id, content, ctx.actor
    )
    return product_out(product)


@router.get("/orders", response_model=list[AdminOrderOut], responses=ERRORS)
async def list_orders(
    ctx: CanRead,
    session: SessionDep,
    order_status: Annotated[list[OrderStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AdminOrderOut]:
    rows = await ShopService(session).orders(ctx.branch_id, order_status, limit)
    return [admin_order_out(order, client) for order, client in rows]


async def _out(session: SessionDep, order_id: uuid.UUID, ctx: AdminContext) -> AdminOrderOut:
    order = await ShopService(session).order(ctx.branch_id, order_id)
    client = await session.get(Client, order.client_id)
    assert client is not None  # noqa: S101 - FK
    return admin_order_out(order, client)


@router.post("/orders/{order_id}/status", response_model=AdminOrderOut, responses=ERRORS)
async def change_order_status(
    order_id: uuid.UUID, body: OrderStatusIn, ctx: CanOrders, session: SessionDep, now: NowDep
) -> AdminOrderOut:
    """paid (confirms the client's claim, or records cash), ready, completed, cancelled."""
    await ShopService(session).set_status(
        ctx.branch_id,
        order_id,
        body.status,
        version=body.version,
        method=body.payment_method,
        actor=ctx.actor,
        now=now,
        note=body.note,
    )
    return await _out(session, order_id, ctx)


@router.post("/orders/{order_id}/reject-payment", response_model=AdminOrderOut, responses=ERRORS)
async def reject_order_payment(
    order_id: uuid.UUID, ctx: CanOrders, session: SessionDep, now: NowDep
) -> AdminOrderOut:
    """The client's money did not arrive: back to 'waiting for payment'."""
    await ShopService(session).reject_claim(ctx.branch_id, order_id, ctx.actor, now)
    return await _out(session, order_id, ctx)
