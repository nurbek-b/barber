"""Salon shop: products, client orders paid by the salon's bank QR, pickup at the salon.

Order lifecycle:
    new ──"I paid"──▶ payment_claimed ──confirm──▶ paid ──▶ ready ──▶ completed
     │                   │ reject ▲ (back to new)     │         │
     └──── cancelled ◀───┴────────────────────────────┴─────────┘
The salon may also record a payment itself (cash at pickup): new → paid.
Stock (when tracked) is taken when the order is placed and returned on cancellation.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.media import get_media_storage, key_from_url, url_for
from app.models import (
    Client,
    Notification,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    Product,
    TelegramOutbox,
    User,
)
from app.models.enums import NotificationType, PaymentMethod, PaymentStatus
from app.notify.templates import format_money
from app.services.audit import Actor, AuditService
from app.services.barbers import PayloadTooLargeError, detect_image_type
from app.services.branches import BranchService

TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.NEW: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAYMENT_CLAIMED: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset({OrderStatus.READY, OrderStatus.COMPLETED, OrderStatus.CANCELLED}),
    OrderStatus.READY: frozenset({OrderStatus.COMPLETED, OrderStatus.CANCELLED}),
    OrderStatus.COMPLETED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}
CLIENT_NOTIFY = (OrderStatus.PAID, OrderStatus.READY, OrderStatus.CANCELLED)
MAX_ORDERS_OPEN = 5


@dataclass(frozen=True, slots=True)
class OrderPaymentInfo:
    order: Order
    qr_url: str | None
    note: str | None
    currency: str
    amount_left: int


def _name(i18n: dict[str, Any], lang: str) -> str:
    return str(i18n.get(lang) or i18n.get("ru") or next(iter(i18n.values()), ""))


class ShopService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ products

    async def products(self, branch_id: uuid.UUID, *, only_active: bool) -> list[Product]:
        query = select(Product).where(Product.branch_id == branch_id)
        if only_active:
            query = query.where(Product.is_active.is_(True))
        rows = await self.session.scalars(query.order_by(Product.sort_order, Product.created_at))
        return list(rows)

    async def product(self, branch_id: uuid.UUID, product_id: uuid.UUID) -> Product:
        product = await self.session.get(Product, product_id)
        if product is None or product.branch_id != branch_id:
            raise NotFoundError("Product not found")
        return product

    async def set_photo(
        self, branch_id: uuid.UUID, product_id: uuid.UUID, content: bytes, actor: Actor
    ) -> Product:
        if self.settings is None:
            raise RuntimeError("settings are required for uploads")
        if len(content) > self.settings.max_upload_bytes:
            raise PayloadTooLargeError()
        extension = detect_image_type(content[:16])
        if extension is None:
            raise ValidationAppError("Only JPEG, PNG or WebP images", code="unsupported_image")
        product = await self.product(branch_id, product_id)
        storage = get_media_storage(self.settings)
        key = f"products/{product.id}-{secrets.token_hex(6)}.{extension}"
        await storage.save(key, content)
        old = product.photo_url
        product.photo_url = url_for(self.settings, key)
        self.audit.record(actor, "product.photo", "product", product.id)
        await self.session.commit()
        old_key = key_from_url(self.settings, old)
        if old_key:
            await storage.delete(old_key)
        return product

    # ------------------------------------------------------------------ client orders

    async def place(
        self,
        branch_id: uuid.UUID,
        client: Client,
        items: Sequence[tuple[uuid.UUID, int]],
        comment: str | None,
        idempotency_key: str,
        actor: Actor,
        now: datetime,
    ) -> tuple[Order, bool]:
        if not idempotency_key or len(idempotency_key) > 64:
            raise ValidationAppError("Idempotency-Key is required", code="idempotency_key_required")
        existing = await self.session.scalar(
            select(Order).where(
                Order.client_id == client.id, Order.idempotency_key == idempotency_key
            )
        )
        if existing is not None:
            return existing, False
        if not client.phone:
            raise ValidationAppError("Share your phone number first", code="phone_required")
        open_orders = await self.session.scalar(
            select(func.count()).where(
                Order.client_id == client.id,
                Order.status.in_([OrderStatus.NEW, OrderStatus.PAYMENT_CLAIMED]),
            )
        )
        if (open_orders or 0) >= MAX_ORDERS_OPEN:
            raise ConflictError("Pay or cancel your open orders first", code="too_many_orders")

        merged: dict[uuid.UUID, int] = {}
        for product_id, quantity in items:
            merged[product_id] = merged.get(product_id, 0) + quantity
        products = {
            p.id: p
            for p in await self.session.scalars(
                select(Product)
                .where(Product.id.in_(list(merged)), Product.branch_id == branch_id)
                .with_for_update()
            )
        }
        lines: list[OrderItem] = []
        for position, (product_id, quantity) in enumerate(merged.items()):
            product = products.get(product_id)
            if product is None or not product.is_active:
                raise ValidationAppError("A product is no longer sold", code="product_unavailable")
            if quantity > 99:
                raise ValidationAppError("Too many items", code="bad_quantity")
            if product.stock is not None:
                if product.stock < quantity:
                    raise ConflictError(
                        "Not enough in stock",
                        code="out_of_stock",
                        details={"product_id": str(product.id), "stock": product.stock},
                    )
                product.stock -= quantity
            lines.append(
                OrderItem(
                    product_id=product.id,
                    name_snapshot=dict(product.name_i18n),
                    price=product.price,
                    quantity=quantity,
                    position=position,
                )
            )
        number = (
            await self.session.scalar(
                select(func.coalesce(func.max(Order.number), 0)).where(Order.branch_id == branch_id)
            )
            or 0
        ) + 1
        order = Order(
            branch_id=branch_id,
            client_id=client.id,
            number=number,
            status=OrderStatus.NEW,
            total=sum(line.price * line.quantity for line in lines),
            comment=(comment or "").strip() or None,
            idempotency_key=idempotency_key,
            items=lines,
        )
        self.session.add(order)
        try:
            await self.session.flush()
        except IntegrityError as exc:  # two orders took the same number at once: retry once
            await self.session.rollback()
            raise ConflictError("Please try again", code="retry") from exc
        self.audit.record(actor, "order.create", "order", order.id, after={"total": order.total})
        await self._notify_admin(order, client, "order_created_admin", now)
        await self.session.commit()
        return order, True

    async def client_orders(self, client: Client, limit: int = 30) -> list[Order]:
        rows = await self.session.scalars(
            select(Order)
            .where(Order.client_id == client.id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def _client_order(self, client: Client, order_id: uuid.UUID) -> Order:
        order = await self.session.scalar(
            select(Order)
            .where(Order.id == order_id, Order.client_id == client.id)
            .with_for_update()
        )
        if order is None:
            raise NotFoundError("Order not found")
        return order

    async def payment_info(self, client: Client, order_id: uuid.UUID) -> OrderPaymentInfo:
        return await self._info(await self._client_order(client, order_id))

    async def _info(self, order: Order) -> OrderPaymentInfo:
        salon = await BranchService(self.session).settings(order.branch_id)
        return OrderPaymentInfo(
            order=order,
            qr_url=salon.payment_qr_url,
            note=salon.payment_note,
            currency=salon.currency,
            amount_left=max(0, order.total - order.paid_amount),
        )

    async def claim(self, client: Client, order_id: uuid.UUID, now: datetime) -> OrderPaymentInfo:
        order = await self._client_order(client, order_id)
        if order.status is not OrderStatus.NEW:
            raise ConflictError("The order is not waiting for payment", code="order_not_new")
        salon = await BranchService(self.session).settings(order.branch_id)
        if not salon.payment_qr_url:
            raise ValidationAppError("The salon doesn't accept QR payments", code="no_payment_qr")
        self.session.add(
            Payment(
                branch_id=order.branch_id,
                order_id=order.id,
                amount=order.total - order.paid_amount,
                method=PaymentMethod.TRANSFER,
                status=PaymentStatus.CLAIMED,
                by_client=True,
            )
        )
        order.status = OrderStatus.PAYMENT_CLAIMED
        order.version += 1
        self.audit.record(Actor.client(client.id), "order.claim", "order", order.id)
        await self._notify_admin(order, client, "order_paid_claimed_admin", now)
        await self.session.commit()
        return await self._info(order)

    async def cancel_by_client(self, client: Client, order_id: uuid.UUID) -> Order:
        order = await self._client_order(client, order_id)
        if order.status is not OrderStatus.NEW:
            raise ConflictError(
                "Paid orders are cancelled by the salon", code="order_not_cancellable"
            )
        await self._cancel(order)
        self.audit.record(Actor.client(client.id), "order.cancel", "order", order.id)
        await self.session.commit()
        return order

    # ------------------------------------------------------------------ salon side

    async def orders(
        self, branch_id: uuid.UUID, statuses: Sequence[OrderStatus] | None, limit: int
    ) -> list[tuple[Order, Client]]:
        query = (
            select(Order, Client)
            .join(Client, Client.id == Order.client_id)
            .where(Order.branch_id == branch_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        if statuses:
            query = query.where(Order.status.in_(statuses))
        return [(order, client) for order, client in (await self.session.execute(query)).all()]

    async def order(self, branch_id: uuid.UUID, order_id: uuid.UUID) -> Order:
        order = await self.session.scalar(
            select(Order)
            .where(Order.id == order_id, Order.branch_id == branch_id)
            .with_for_update()
        )
        if order is None:
            raise NotFoundError("Order not found")
        return order

    async def set_status(
        self,
        branch_id: uuid.UUID,
        order_id: uuid.UUID,
        status: OrderStatus,
        *,
        version: int,
        method: PaymentMethod | None,
        actor: Actor,
        now: datetime,
    ) -> Order:
        order = await self.order(branch_id, order_id)
        if order.version != version:
            raise ConflictError("The order was changed, reload it", code="version_conflict")
        if status not in TRANSITIONS[order.status]:
            raise ConflictError(
                f"Cannot change status from {order.status.value} to {status.value}",
                code="invalid_transition",
            )
        previous = order.status
        claimed = await self.session.scalars(
            select(Payment).where(
                Payment.order_id == order.id, Payment.status == PaymentStatus.CLAIMED
            )
        )
        if status is OrderStatus.PAID:
            # confirms the client's claim, or records money the salon took itself
            open_claims = list(claimed)
            for payment in open_claims:
                payment.status = PaymentStatus.CONFIRMED
                payment.decided_at = now
                payment.decided_by = actor.id
            left = order.total - order.paid_amount
            if not open_claims and left > 0:
                self.session.add(
                    Payment(
                        branch_id=order.branch_id,
                        order_id=order.id,
                        amount=left,
                        method=method or PaymentMethod.CASH,
                        status=PaymentStatus.CONFIRMED,
                        decided_at=now,
                        decided_by=actor.id,
                    )
                )
            order.paid_amount = order.total
        elif status is OrderStatus.CANCELLED:
            for payment in claimed:
                payment.status = PaymentStatus.REJECTED
                payment.decided_at = now
                payment.decided_by = actor.id
            await self._cancel(order)
        order.status = status
        order.version += 1
        self.audit.record(
            actor,
            "order.status",
            "order",
            order.id,
            before={"status": previous.value},
            after={"status": status.value},
        )
        if status in CLIENT_NOTIFY:
            await self._notify_client(order, f"order_{status.value}_client")
        await self.session.commit()
        return order

    async def reject_claim(
        self, branch_id: uuid.UUID, order_id: uuid.UUID, actor: Actor, now: datetime
    ) -> Order:
        """The money did not arrive: back to 'waiting for payment' and the client is told."""
        order = await self.order(branch_id, order_id)
        if order.status is not OrderStatus.PAYMENT_CLAIMED:
            raise ConflictError("No payment to check", code="no_claim")
        for payment in await self.session.scalars(
            select(Payment).where(
                Payment.order_id == order.id, Payment.status == PaymentStatus.CLAIMED
            )
        ):
            payment.status = PaymentStatus.REJECTED
            payment.decided_at = now
            payment.decided_by = actor.id
        order.status = OrderStatus.NEW
        order.version += 1
        self.audit.record(actor, "order.reject_payment", "order", order.id)
        await self._notify_client(order, "order_payment_rejected_client")
        await self.session.commit()
        return order

    async def _cancel(self, order: Order) -> None:
        for line in order.items:
            if line.product_id is None:
                continue
            product = await self.session.get(Product, line.product_id, with_for_update=True)
            if product is not None and product.stock is not None:
                product.stock += line.quantity
        order.status = OrderStatus.CANCELLED
        order.version += 1

    # ------------------------------------------------------------------ messages

    def _items_text(self, order: Order, lang: str) -> str:
        return ", ".join(
            f"{_name(line.name_snapshot, lang)} × {line.quantity}" for line in order.items
        )

    async def _notify_admin(
        self, order: Order, client: Client, template: str, now: datetime
    ) -> None:
        salon = await BranchService(self.session).settings(order.branch_id)
        values = {
            "order_id": str(order.id),
            "number": order.number,
            "client": client.name,
            "phone": client.phone or "",
            "items": self._items_text(order, salon.default_language),
            "total": format_money(order.total, salon.currency),
        }
        notification = Notification(
            branch_id=order.branch_id,
            type=NotificationType.ORDER_CREATED,
            payload={**values, "event": template},
            created_at=now,
        )
        self.session.add(notification)
        if salon.admin_chat_id:
            self.session.add(
                TelegramOutbox(
                    chat_id=salon.admin_chat_id,
                    template_key=template,
                    language=salon.default_language,
                    payload=values,
                    dedupe_key=f"{template}:{order.id}:{order.version}",
                )
            )
        await self.session.flush()

    async def _notify_client(self, order: Order, template: str) -> None:
        client = await self.session.get(Client, order.client_id)
        user = await self.session.get(User, client.user_id) if client and client.user_id else None
        if client is None or user is None or user.bot_blocked:
            return
        salon = await BranchService(self.session).settings(order.branch_id)
        self.session.add(
            TelegramOutbox(
                chat_id=user.telegram_id,
                template_key=template,
                language=client.language,
                payload={
                    "number": order.number,
                    "items": self._items_text(order, client.language),
                    "total": format_money(order.total, salon.currency),
                    "salon": salon.name,
                },
                dedupe_key=f"{template}:{order.id}:{order.version}",
            )
        )


def idempotency_fingerprint(items: Sequence[tuple[uuid.UUID, int]]) -> str:
    return hashlib.sha256(repr(sorted(items)).encode()).hexdigest()
