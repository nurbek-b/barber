"""Bonus math. Pure functions; amounts are integer minor units, percentages basis points."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from app.domain.pricing import percent_of

_FAR_FUTURE = datetime.max.replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class Lot:
    """A credit transaction with what is left of it."""

    tx_id: uuid.UUID
    remaining: int
    expires_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Allocation:
    tx_id: uuid.UUID
    amount: int


class InsufficientBonusError(ValueError):
    def __init__(self, requested: int, available: int) -> None:
        super().__init__(f"requested {requested}, available {available}")
        self.requested = requested
        self.available = available


def _fifo_key(lot: Lot) -> tuple[bool, datetime, datetime, str]:
    # Soonest-expiring first; lots without expiry last; ties by age.
    expires = lot.expires_at.replace(tzinfo=None) if lot.expires_at else _FAR_FUTURE
    return (lot.expires_at is None, expires, lot.created_at.replace(tzinfo=None), str(lot.tx_id))


def usable_lots(lots: Sequence[Lot], now: datetime) -> list[Lot]:
    return sorted(
        (
            lot
            for lot in lots
            if lot.remaining > 0 and (lot.expires_at is None or lot.expires_at > now)
        ),
        key=_fifo_key,
    )


def allocate_fifo(lots: Sequence[Lot], amount: int, now: datetime) -> list[Allocation]:
    """Take `amount` from the lots expiring soonest. Expired lots are never used."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    available = usable_lots(lots, now)
    total = sum(lot.remaining for lot in available)
    if total < amount:
        raise InsufficientBonusError(amount, total)
    result: list[Allocation] = []
    left = amount
    for lot in available:
        if left == 0:
            break
        take = min(lot.remaining, left)
        result.append(Allocation(lot.tx_id, take))
        left -= take
    return result


def expired_lots(lots: Sequence[Lot], now: datetime) -> list[Lot]:
    return [
        lot
        for lot in lots
        if lot.remaining > 0 and lot.expires_at is not None and lot.expires_at <= now
    ]


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------


class LevelRule(StrEnum):
    ANY = "any"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class Level:
    id: uuid.UUID
    min_visits: int
    min_spent: int
    cashback_bp: int
    sort_order: int


def reaches(level: Level, visits: int, spent: int, rule: LevelRule) -> bool:
    by_visits = visits >= level.min_visits
    by_spent = spent >= level.min_spent
    if level.min_visits == 0 and level.min_spent == 0:
        return True
    if rule is LevelRule.ALL:
        return by_visits and by_spent
    # ANY: a zero threshold means "not used", otherwise it would make every level free
    checks = []
    if level.min_visits > 0:
        checks.append(by_visits)
    if level.min_spent > 0:
        checks.append(by_spent)
    return any(checks)


def _ordered(levels: Sequence[Level]) -> list[Level]:
    return sorted(levels, key=lambda lvl: (lvl.sort_order, lvl.min_spent, lvl.min_visits))


def resolve_level(
    levels: Sequence[Level],
    visits: int,
    spent: int,
    rule: LevelRule,
    current: uuid.UUID | None = None,
) -> Level | None:
    """Highest level reached. Never downgrades below `current` (levels are a reward)."""
    ordered = _ordered(levels)
    best: Level | None = None
    for level in ordered:
        if reaches(level, visits, spent, rule):
            best = level
    if current is not None:
        index = {lvl.id: i for i, lvl in enumerate(ordered)}
        if current in index and (best is None or index[best.id] < index[current]):
            return ordered[index[current]]
    return best


@dataclass(frozen=True, slots=True)
class LevelProgress:
    next_level: Level | None
    visits_left: int
    spent_left: int


def progress_to_next(
    levels: Sequence[Level], current: Level | None, visits: int, spent: int, rule: LevelRule
) -> LevelProgress:
    ordered = _ordered(levels)
    start = (
        0
        if current is None
        else next((i + 1 for i, lvl in enumerate(ordered) if lvl.id == current.id), 0)
    )
    for level in ordered[start:]:
        if not reaches(level, visits, spent, rule):
            return LevelProgress(
                next_level=level,
                visits_left=max(0, level.min_visits - visits),
                spent_left=max(0, level.min_spent - spent),
            )
    return LevelProgress(next_level=None, visits_left=0, spent_left=0)


def cashback(paid: int, level: Level | None, base_bp: int) -> int:
    """Cashback on the amount paid with money (bonuses are not cashbacked)."""
    bp = level.cashback_bp if level is not None else base_bp
    return percent_of(max(paid, 0), bp)


# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------


def lot_expiry(now: datetime, lifetime_days: int | None) -> datetime | None:
    return now + timedelta(days=lifetime_days) if lifetime_days else None


def birthday_in_year(birthday: date, year: int) -> date:
    """Feb 29 birthdays are celebrated on Feb 28 in non-leap years."""
    try:
        return birthday.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def birthday_due(birthday: date, today: date, days_before: int) -> int | None:
    """Return the year whose birthday bonus is due today, or None."""
    for year in (today.year, today.year + 1):
        celebration = birthday_in_year(birthday, year)
        if celebration - timedelta(days=days_before) == today:
            return year
    return None
