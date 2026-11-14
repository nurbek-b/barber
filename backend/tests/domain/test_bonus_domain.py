from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.bonus import (
    Allocation,
    InsufficientBonusError,
    Level,
    LevelRule,
    Lot,
    allocate_fifo,
    birthday_due,
    birthday_in_year,
    cashback,
    expired_lots,
    lot_expiry,
    progress_to_next,
    resolve_level,
)
from app.domain.pricing import max_bonus_spend, percent_of

NOW = datetime(2026, 12, 1, tzinfo=UTC)


def lot(n: int, remaining: int, expires_in_days: int | None, age_days: int = 0) -> Lot:
    return Lot(
        tx_id=uuid.UUID(int=n),
        remaining=remaining,
        expires_at=NOW + timedelta(days=expires_in_days) if expires_in_days is not None else None,
        created_at=NOW - timedelta(days=age_days),
    )


# ---------------------------------------------------------------------------
# FIFO
# ---------------------------------------------------------------------------


def test_fifo_takes_soonest_expiring_first() -> None:
    lots = [lot(1, 500, 90), lot(2, 300, 10), lot(3, 1000, None), lot(4, 200, 30)]
    assert allocate_fifo(lots, 600, NOW) == [
        Allocation(uuid.UUID(int=2), 300),
        Allocation(uuid.UUID(int=4), 200),
        Allocation(uuid.UUID(int=1), 100),
    ]


def test_fifo_never_expiring_lots_last() -> None:
    lots = [lot(1, 100, None), lot(2, 100, 365)]
    assert [a.tx_id.int for a in allocate_fifo(lots, 150, NOW)] == [2, 1]


def test_fifo_same_expiry_older_first() -> None:
    lots = [lot(1, 100, 10, age_days=1), lot(2, 100, 10, age_days=5)]
    assert allocate_fifo(lots, 50, NOW) == [Allocation(uuid.UUID(int=2), 50)]


def test_fifo_skips_expired_and_empty() -> None:
    lots = [lot(1, 500, -1), lot(2, 0, 10), lot(3, 100, 10)]
    assert allocate_fifo(lots, 100, NOW) == [Allocation(uuid.UUID(int=3), 100)]
    with pytest.raises(InsufficientBonusError) as exc:
        allocate_fifo(lots, 101, NOW)
    assert exc.value.available == 100


def test_fifo_exact_balance_and_invalid_amount() -> None:
    lots = [lot(1, 100, 10), lot(2, 50, 20)]
    assert sum(a.amount for a in allocate_fifo(lots, 150, NOW)) == 150
    with pytest.raises(ValueError, match="positive"):
        allocate_fifo(lots, 0, NOW)


def test_expired_lots() -> None:
    lots = [lot(1, 100, -1), lot(2, 0, -1), lot(3, 100, 1), lot(4, 50, None)]
    assert [item.tx_id.int for item in expired_lots(lots, NOW)] == [1]


# ---------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------

BRONZE = Level(uuid.UUID(int=10), 0, 0, 300, 0)
SILVER = Level(uuid.UUID(int=11), 5, 1_000_000, 500, 1)
GOLD = Level(uuid.UUID(int=12), 15, 3_000_000, 700, 2)
LEVELS = [GOLD, BRONZE, SILVER]  # unsorted on purpose


@pytest.mark.parametrize(
    ("visits", "spent", "rule", "expected"),
    [
        (0, 0, LevelRule.ANY, BRONZE),
        (5, 0, LevelRule.ANY, SILVER),  # visits alone are enough with ANY
        (0, 1_000_000, LevelRule.ANY, SILVER),  # money alone is enough with ANY
        (5, 0, LevelRule.ALL, BRONZE),  # ALL needs both
        (5, 1_000_000, LevelRule.ALL, SILVER),
        (20, 999_999, LevelRule.ALL, BRONZE),
        (15, 3_000_000, LevelRule.ALL, GOLD),
        (100, 0, LevelRule.ANY, GOLD),
    ],
)
def test_resolve_level(visits: int, spent: int, rule: LevelRule, expected: Level) -> None:
    assert resolve_level(LEVELS, visits, spent, rule) == expected


def test_threshold_zero_means_not_used_with_any() -> None:
    visits_only = Level(uuid.UUID(int=20), 3, 0, 400, 1)
    assert resolve_level([BRONZE, visits_only], 2, 10**9, LevelRule.ANY) == BRONZE
    assert resolve_level([BRONZE, visits_only], 3, 0, LevelRule.ANY) == visits_only


def test_no_downgrade() -> None:
    assert resolve_level(LEVELS, 0, 0, LevelRule.ANY, current=GOLD.id) == GOLD


def test_no_levels() -> None:
    assert resolve_level([], 10, 10, LevelRule.ANY) is None


def test_progress() -> None:
    progress = progress_to_next(LEVELS, SILVER, 7, 1_200_000, LevelRule.ALL)
    assert progress.next_level == GOLD
    assert progress.visits_left == 8
    assert progress.spent_left == 1_800_000
    top = progress_to_next(LEVELS, GOLD, 30, 10**8, LevelRule.ANY)
    assert top.next_level is None


def test_cashback_and_rounding() -> None:
    assert cashback(123_456, SILVER, 100) == 6_172  # 5% of 1234.56 = 61.7280 → 61.72
    assert cashback(100_000, None, 250) == 2_500  # no level → base rate
    assert cashback(-5, SILVER, 100) == 0
    assert percent_of(1, 9_999) == 0  # always rounds down


def test_max_bonus_spend() -> None:
    assert max_bonus_spend(150_000, 100_000, 3_000, True) == 45_000
    assert max_bonus_spend(150_000, 10_000, 3_000, True) == 10_000
    assert max_bonus_spend(150_000, 100_000, 3_000, False) == 0


# ---------------------------------------------------------------------------
# dates
# ---------------------------------------------------------------------------


def test_lot_expiry() -> None:
    assert lot_expiry(NOW, 180) == NOW + timedelta(days=180)
    assert lot_expiry(NOW, None) is None


def test_birthday_leap_day() -> None:
    assert birthday_in_year(date(2000, 2, 29), 2027) == date(2027, 2, 28)
    assert birthday_in_year(date(2000, 2, 29), 2028) == date(2028, 2, 29)


def test_birthday_due() -> None:
    bday = date(1990, 12, 10)
    assert birthday_due(bday, date(2026, 12, 10), 0) == 2026
    assert birthday_due(bday, date(2026, 12, 7), 3) == 2026
    assert birthday_due(bday, date(2026, 12, 8), 3) is None
    # 3 days before Jan 2 → previous calendar year
    assert birthday_due(date(1990, 1, 2), date(2026, 12, 30), 3) == 2027
