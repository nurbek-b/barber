"""Money math in integer minor units (tyiyn). Percentages are basis points (500 = 5%)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

BP_DENOMINATOR = 10_000


def percent_of(amount: int, bp: int) -> int:
    """amount * bp / 10000 rounded down. Both are non-negative integers."""
    if amount < 0 or bp < 0:
        raise ValueError("amount and bp must be non-negative")
    return amount * bp // BP_DENOMINATOR


@dataclass(frozen=True, slots=True)
class PriceLine:
    service_id: uuid.UUID
    name: dict[str, str]
    duration_min: int
    price: int


@dataclass(frozen=True, slots=True)
class Quote:
    lines: tuple[PriceLine, ...]
    subtotal: int
    duration_min: int
    bonus_balance: int
    max_bonus_spend: int

    def total_due(self, bonus_spent: int) -> int:
        return self.subtotal - bonus_spent


def max_bonus_spend(subtotal: int, balance: int, max_spend_bp: int, enabled: bool) -> int:
    """How many bonus units may pay for this check: min(balance, max% of the check)."""
    if not enabled or subtotal <= 0 or balance <= 0:
        return 0
    return min(balance, percent_of(subtotal, max_spend_bp))


def build_quote(
    lines: Sequence[PriceLine], *, bonus_balance: int, max_spend_bp: int, bonus_enabled: bool
) -> Quote:
    subtotal = sum(line.price for line in lines)
    return Quote(
        lines=tuple(lines),
        subtotal=subtotal,
        duration_min=sum(line.duration_min for line in lines),
        bonus_balance=bonus_balance,
        max_bonus_spend=max_bonus_spend(subtotal, bonus_balance, max_spend_bp, bonus_enabled),
    )
