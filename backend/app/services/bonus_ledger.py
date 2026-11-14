"""Append-only bonus ledger.

Invariants
----------
* Every change is a row in bonus_transactions; rows are never updated or deleted.
* clients.bonus_balance == SUM(bonus_transactions.amount) — maintained in the same transaction
  after locking the client row (SELECT … FOR UPDATE), so concurrent operations serialize.
* Debits consume credit "lots" FIFO by expiry; consumption is recorded in
  bonus_lot_consumptions (also append-only). Remaining of a lot = amount − Σ consumptions.
* dedupe_key makes one-off credits (earn per booking, birthday per year, welcome, referral)
  idempotent: a repeated call is a no-op.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationAppError
from app.domain.bonus import Allocation, InsufficientBonusError, Lot, allocate_fifo
from app.models import BonusLotConsumption, BonusTransaction, Client
from app.models.enums import BonusTxType

REFUND_MIN_LIFETIME = timedelta(days=7)

CREDIT_TYPES = frozenset(
    {
        BonusTxType.EARN,
        BonusTxType.REFUND,
        BonusTxType.MANUAL,
        BonusTxType.REFERRAL,
        BonusTxType.WELCOME,
        BonusTxType.BIRTHDAY,
    }
)
DEBIT_TYPES = frozenset({BonusTxType.SPEND, BonusTxType.EXPIRE, BonusTxType.MANUAL})


class NotEnoughBonusesError(ValidationAppError):
    code = "not_enough_bonuses"
    message = "Not enough bonuses"


class BonusLedger:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_client(self, client_id: uuid.UUID) -> Client:
        client = await self.session.scalar(
            select(Client)
            .where(Client.id == client_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if client is None:
            raise NotFoundError("Client not found")
        return client

    async def lots(self, client_id: uuid.UUID) -> list[Lot]:
        consumed = func.coalesce(func.sum(BonusLotConsumption.amount), 0)
        rows = await self.session.execute(
            select(
                BonusTransaction.id,
                (BonusTransaction.amount - consumed).label("remaining"),
                BonusTransaction.expires_at,
                BonusTransaction.created_at,
            )
            .outerjoin(BonusLotConsumption, BonusLotConsumption.lot_tx_id == BonusTransaction.id)
            .where(BonusTransaction.client_id == client_id, BonusTransaction.amount > 0)
            .group_by(BonusTransaction.id)
            .having(BonusTransaction.amount - consumed > 0)
        )
        return [
            Lot(
                tx_id=row.id,
                remaining=int(row.remaining),
                expires_at=row.expires_at,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def _dedupe_exists(self, key: str | None) -> bool:
        if key is None:
            return False
        found = await self.session.scalar(
            select(BonusTransaction.id).where(BonusTransaction.dedupe_key == key)
        )
        return found is not None

    def _append(
        self,
        client: Client,
        tx_type: BonusTxType,
        amount: int,
        now: datetime,
        *,
        expires_at: datetime | None = None,
        booking_id: uuid.UUID | None = None,
        comment: str | None = None,
        admin_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
    ) -> BonusTransaction:
        balance = client.bonus_balance + amount
        if balance < 0:  # pragma: no cover - guarded by callers
            raise NotEnoughBonusesError()
        client.bonus_balance = balance
        tx = BonusTransaction(
            id=uuid.uuid4(),
            client_id=client.id,
            type=tx_type,
            amount=amount,
            balance_after=balance,
            booking_id=booking_id,
            expires_at=expires_at,
            comment=comment,
            created_by_admin_id=admin_id,
            dedupe_key=dedupe_key,
            created_at=now,
        )
        self.session.add(tx)
        return tx

    async def credit(
        self,
        client: Client,
        tx_type: BonusTxType,
        amount: int,
        now: datetime,
        *,
        expires_at: datetime | None = None,
        booking_id: uuid.UUID | None = None,
        comment: str | None = None,
        admin_id: uuid.UUID | None = None,
        dedupe_key: str | None = None,
    ) -> BonusTransaction | None:
        """Returns None when amount is 0 or the dedupe key was already used.
        The caller must hold the client lock (see `lock_client`)."""
        if tx_type not in CREDIT_TYPES:
            raise ValueError(f"{tx_type} is not a credit")
        if amount <= 0 or await self._dedupe_exists(dedupe_key):
            return None
        tx = self._append(
            client,
            tx_type,
            amount,
            now,
            expires_at=expires_at,
            booking_id=booking_id,
            comment=comment,
            admin_id=admin_id,
            dedupe_key=dedupe_key,
        )
        await self.session.flush()
        return tx

    async def debit(
        self,
        client: Client,
        tx_type: BonusTxType,
        amount: int,
        now: datetime,
        *,
        booking_id: uuid.UUID | None = None,
        comment: str | None = None,
        admin_id: uuid.UUID | None = None,
        allocations: Sequence[Allocation] | None = None,
    ) -> BonusTransaction:
        """FIFO debit. `allocations` lets the expiry job consume specific (expired) lots."""
        if tx_type not in DEBIT_TYPES:
            raise ValueError(f"{tx_type} is not a debit")
        if amount <= 0:
            raise ValueError("amount must be positive")
        if allocations is None:
            try:
                allocations = allocate_fifo(await self.lots(client.id), amount, now)
            except InsufficientBonusError as exc:
                raise NotEnoughBonusesError(
                    details={"requested": exc.requested, "available": exc.available}
                ) from exc
        if sum(item.amount for item in allocations) != amount:
            raise ValueError("allocations do not add up")
        tx = self._append(
            client,
            tx_type,
            -amount,
            now,
            booking_id=booking_id,
            comment=comment,
            admin_id=admin_id,
        )
        await self.session.flush()  # no ORM relationship: insert the debit before its rows
        self.session.add_all(
            BonusLotConsumption(lot_tx_id=item.tx_id, consumer_tx_id=tx.id, amount=item.amount)
            for item in allocations
        )
        await self.session.flush()
        return tx

    async def refundable_for_booking(self, client_id: uuid.UUID, booking_id: uuid.UUID) -> int:
        spent = await self._total_spent(client_id, booking_id)
        refunded = await self.session.scalar(
            select(func.coalesce(func.sum(BonusTransaction.amount), 0)).where(
                BonusTransaction.client_id == client_id,
                BonusTransaction.booking_id == booking_id,
                BonusTransaction.type == BonusTxType.REFUND,
            )
        )
        return spent - int(refunded or 0)

    async def refund_booking(
        self, client: Client, booking_id: uuid.UUID, now: datetime, amount: int | None = None
    ) -> int:
        """Return bonuses spent on a booking (all, or `amount`). Refunded lots keep their
        original expiry, but get at least REFUND_MIN_LIFETIME so the client can use them."""
        refundable = await self.refundable_for_booking(client.id, booking_id)
        to_refund = refundable if amount is None else min(amount, refundable)
        if to_refund <= 0:
            return 0
        rows = await self.session.execute(
            select(BonusLotConsumption.amount, BonusTransaction.expires_at)
            .join(BonusTransaction, BonusTransaction.id == BonusLotConsumption.lot_tx_id)
            .join(
                spend := BonusTransaction.__table__.alias("spend"),
                spend.c.id == BonusLotConsumption.consumer_tx_id,
            )
            .where(
                spend.c.booking_id == booking_id,
                spend.c.type == BonusTxType.SPEND.value,
                spend.c.client_id == client.id,
            )
            .order_by(BonusTransaction.expires_at.desc().nulls_first())
        )
        # Earlier partial refunds consumed the latest-expiring parts first: skip them.
        skip = (await self._total_spent(client.id, booking_id)) - refundable
        left = to_refund
        floor = now + REFUND_MIN_LIFETIME
        for consumed, expires_at in rows:
            portion = int(consumed)
            if skip > 0:
                used = min(skip, portion)
                skip -= used
                portion -= used
            if portion <= 0 or left <= 0:
                continue
            take = min(portion, left)
            expiry = None if expires_at is None else max(expires_at, floor)
            self._append(
                client, BonusTxType.REFUND, take, now, expires_at=expiry, booking_id=booking_id
            )
            left -= take
        if left > 0:  # pragma: no cover - consumptions always cover the spend
            self._append(
                client, BonusTxType.REFUND, left, now, expires_at=floor, booking_id=booking_id
            )
        await self.session.flush()
        return to_refund

    async def _total_spent(self, client_id: uuid.UUID, booking_id: uuid.UUID) -> int:
        spent = await self.session.scalar(
            select(func.coalesce(-func.sum(BonusTransaction.amount), 0)).where(
                BonusTransaction.client_id == client_id,
                BonusTransaction.booking_id == booking_id,
                BonusTransaction.type == BonusTxType.SPEND,
            )
        )
        return int(spent or 0)

    async def ledger_sum(self, client_id: uuid.UUID) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(BonusTransaction.amount), 0)).where(
                BonusTransaction.client_id == client_id
            )
        )
        return int(total or 0)
