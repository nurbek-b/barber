"""Response builders for the shop (Mini App and admin)."""

from __future__ import annotations

from app.models import Client, Order, Product
from app.schemas.shop import AdminOrderOut, OrderItemOut, OrderOut, ProductOut


def product_out(product: Product) -> ProductOut:
    return ProductOut(
        id=product.id,
        name_i18n=product.name_i18n,
        description_i18n=product.description_i18n or {},
        price=product.price,
        photo_url=product.photo_url,
        stock=product.stock,
        is_active=product.is_active,
        sort_order=product.sort_order,
    )


def order_out(order: Order) -> OrderOut:
    return OrderOut(
        id=order.id,
        number=order.number,
        status=order.status,
        items=[
            OrderItemOut(
                product_id=line.product_id,
                name_i18n=line.name_snapshot,
                price=line.price,
                quantity=line.quantity,
            )
            for line in order.items
        ],
        total=order.total,
        paid_amount=order.paid_amount,
        comment=order.comment,
        created_at=order.created_at,
        version=order.version,
        delivery=order.delivery,
        address=order.address,
        delivery_fee=order.delivery_fee,
        shipping_note=order.shipping_note,
    )


def admin_order_out(order: Order, client: Client) -> AdminOrderOut:
    return AdminOrderOut(
        **order_out(order).model_dump(),
        client_id=client.id,
        client_name=client.name,
        client_phone=client.phone,
    )
