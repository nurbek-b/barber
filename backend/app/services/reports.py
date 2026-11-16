"""Dashboard metrics and financial reports. Money = integer minor units.

Revenue is what clients paid with money: SUM(paid_amount) of completed visits, attributed to
the local date of the visit. Bonuses are reported separately (bonus_spent).
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, cast, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.slots import local_day_bounds, working_intervals
from app.models import Barber, Booking, BookingService, Client
from app.models.enums import BookingKind, BookingStatus
from app.repositories.schedule import ScheduleRepository
from app.services.branches import BranchService
from app.services.schedule import to_domain_schedule

COUNTED = (BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.COMPLETED)


@dataclass(slots=True)
class Totals:
    bookings: int = 0
    subtotal: int = 0
    bonus_spent: int = 0
    discount: int = 0
    total_due: int = 0
    paid: int = 0
    master_share: int = 0

    def add(self, booking: Booking, master_share: int = 0) -> None:
        self.bookings += 1
        self.subtotal += booking.subtotal
        self.bonus_spent += booking.bonus_spent
        self.discount += booking.discount
        self.total_due += booking.total_due
        self.paid += booking.paid_amount or 0
        self.master_share += master_share


def master_share(subtotal: int, commission_bp: int) -> int:
    """Barber's share of the services price (before bonuses), rounded half up to a tyiyn.

    Paying part of the bill with bonuses is the salon's discount, not the barber's.
    """
    return (subtotal * commission_bp + 5_000) // 10_000


@dataclass(slots=True)
class FinanceReport:
    date_from: date
    date_to: date
    currency: str
    totals: Totals
    by_barber: list[tuple[uuid.UUID, str, int, Totals]]  # id, name, current commission_bp
    by_service: list[tuple[uuid.UUID | None, dict[str, str], int, int]]
    by_method: list[tuple[str | None, int, int]]
    daily: list[tuple[date, int, int]]
    rows: list[dict[str, Any]] = field(default_factory=list)


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.branches = BranchService(session)

    def _local_date(self, tz: str) -> Any:
        return cast(func.timezone(tz, Booking.start_at), Date)

    async def _revenue_between(
        self, branch_id: uuid.UUID, start: datetime, end: datetime
    ) -> tuple[int, int]:
        row = (
            await self.session.execute(
                select(func.coalesce(func.sum(Booking.paid_amount), 0), func.count()).where(
                    Booking.branch_id == branch_id,
                    Booking.status == BookingStatus.COMPLETED,
                    Booking.start_at >= start,
                    Booking.start_at < end,
                )
            )
        ).one()
        return int(row[0]), int(row[1])

    async def dashboard(self, branch_id: uuid.UUID, now: datetime) -> dict[str, Any]:
        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        today = now.astimezone(tz).date()
        day = local_day_bounds(today, tz)
        week_start = local_day_bounds(today - timedelta(days=today.weekday()), tz).start
        month_start = local_day_bounds(today.replace(day=1), tz).start

        status_rows = await self.session.execute(
            select(Booking.status, func.count())
            .where(
                Booking.branch_id == branch_id,
                Booking.kind == BookingKind.APPOINTMENT,
                Booking.start_at >= day.start,
                Booking.start_at < day.end,
            )
            .group_by(Booking.status)
        )
        by_status = {status.value: int(count) for status, count in status_rows.all()}

        revenue_day, _ = await self._revenue_between(branch_id, day.start, day.end)
        revenue_week, _ = await self._revenue_between(branch_id, week_start, day.end)
        revenue_month, visits_month = await self._revenue_between(branch_id, month_start, day.end)
        new_clients = await self.session.scalar(
            select(func.count())
            .select_from(Client)
            .where(Client.branch_id == branch_id, Client.created_at >= month_start)
        )

        chart_start = today - timedelta(days=29)
        daily = await self._daily(branch_id, salon.timezone, chart_start, today)

        barbers = (
            (
                await self.session.execute(
                    select(Barber)
                    .where(Barber.branch_id == branch_id, Barber.is_active.is_(True))
                    .order_by(Barber.sort_order, Barber.name)
                )
            )
            .scalars()
            .all()
        )
        load = await self._load(barbers, today, tz, day.start, day.end)

        upcoming_rows = await self.session.execute(
            select(Booking, Barber.name, Client.name)
            .join(Barber, Barber.id == Booking.barber_id)
            .outerjoin(Client, Client.id == Booking.client_id)
            .where(
                Booking.branch_id == branch_id,
                Booking.kind == BookingKind.APPOINTMENT,
                Booking.status.in_((BookingStatus.PENDING, BookingStatus.CONFIRMED)),
                Booking.start_at >= now,
                Booking.start_at < day.end,
            )
            .order_by(Booking.start_at)
            .limit(10)
        )
        upcoming = [
            {
                "id": str(booking.id),
                "start_at": booking.start_at.isoformat(),
                "barber": barber_name,
                "client": client_name,
                "total_due": booking.total_due,
                "status": booking.status.value,
            }
            for booking, barber_name, client_name in upcoming_rows.all()
        ]
        return {
            "today": today,
            "timezone": salon.timezone,
            "currency": salon.currency,
            "bookings_today": sum(
                count for status, count in by_status.items() if status in {s.value for s in COUNTED}
            ),
            "bookings_today_by_status": by_status,
            "revenue_day": revenue_day,
            "revenue_week": revenue_week,
            "revenue_month": revenue_month,
            "average_check": revenue_month // visits_month if visits_month else 0,
            "new_clients_month": int(new_clients or 0),
            "barbers": load,
            "revenue_chart": [
                {"date": d, "revenue": revenue, "bookings": count} for d, revenue, count in daily
            ],
            "upcoming": upcoming,
        }

    async def _load(
        self,
        barbers: Sequence[Barber],
        today: date,
        tz: ZoneInfo,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        ids = [barber.id for barber in barbers]
        if not ids:
            return []
        schedules = ScheduleRepository(self.session)
        weekly = await schedules.weekly_for(ids)
        exceptions = await schedules.exceptions_for(ids, today - timedelta(days=1), today)
        booked = (
            await self.session.execute(
                select(Booking.barber_id, Booking.start_at, Booking.end_at).where(
                    Booking.barber_id.in_(ids),
                    Booking.kind == BookingKind.APPOINTMENT,
                    Booking.status.in_(COUNTED),
                    Booking.start_at < end,
                    Booking.end_at > start,
                )
            )
        ).all()
        minutes: dict[uuid.UUID, int] = defaultdict(int)
        counts: dict[uuid.UUID, int] = defaultdict(int)
        for barber_id, b_start, b_end in booked:
            minutes[barber_id] += int((min(b_end, end) - max(b_start, start)).total_seconds() // 60)
            counts[barber_id] += 1
        result = []
        for barber in barbers:
            schedule = to_domain_schedule(
                [row for row in weekly if row.barber_id == barber.id],
                [row for row in exceptions if row.barber_id == barber.id],
            )
            working = sum(
                int((min(i.end, end) - max(i.start, start)).total_seconds() // 60)
                for i in working_intervals(today, schedule, tz)
                if i.end > start and i.start < end
            )
            busy = minutes[barber.id]
            result.append(
                {
                    "barber_id": barber.id,
                    "name": barber.name,
                    "booked_minutes": busy,
                    "working_minutes": working,
                    "load_percent": min(100, round(busy * 100 / working)) if working else 0,
                    "bookings": counts[barber.id],
                }
            )
        return result

    async def _daily(
        self, branch_id: uuid.UUID, tz_name: str, first: date, last: date
    ) -> list[tuple[date, int, int]]:
        tz = ZoneInfo(tz_name)
        local_date = self._local_date(tz_name)
        rows = await self.session.execute(
            select(local_date, func.coalesce(func.sum(Booking.paid_amount), 0), func.count())
            .where(
                Booking.branch_id == branch_id,
                Booking.status == BookingStatus.COMPLETED,
                Booking.start_at >= local_day_bounds(first, tz).start,
                Booking.start_at < local_day_bounds(last, tz).end,
            )
            .group_by(local_date)
        )
        by_day = {row[0]: (int(row[1]), int(row[2])) for row in rows.all()}
        days = (last - first).days + 1
        return [
            (first + timedelta(days=i), *by_day.get(first + timedelta(days=i), (0, 0)))
            for i in range(days)
        ]

    async def finance(
        self,
        branch_id: uuid.UUID,
        date_from: date,
        date_to: date,
        barber_ids: Sequence[uuid.UUID] | None = None,
        with_rows: bool = False,
    ) -> FinanceReport:
        salon = await self.branches.settings(branch_id)
        tz = ZoneInfo(salon.timezone)
        start = local_day_bounds(date_from, tz).start
        end = local_day_bounds(date_to, tz).end
        query = (
            select(Booking, Barber.name, Barber.commission_bp, Client.name, Client.phone)
            .join(Barber, Barber.id == Booking.barber_id)
            .outerjoin(Client, Client.id == Booking.client_id)
            .where(
                Booking.branch_id == branch_id,
                Booking.kind == BookingKind.APPOINTMENT,
                Booking.status == BookingStatus.COMPLETED,
                Booking.start_at >= start,
                Booking.start_at < end,
            )
            .order_by(Booking.start_at)
        )
        if barber_ids:
            query = query.where(Booking.barber_id.in_(barber_ids))
        rows = (await self.session.execute(query)).all()

        totals = Totals()
        per_barber: dict[uuid.UUID, tuple[str, int, Totals]] = {}
        per_method: dict[str | None, list[int]] = defaultdict(lambda: [0, 0])
        export_rows: list[dict[str, Any]] = []
        for booking, barber_name, barber_bp, client_name, client_phone in rows:
            # rate fixed at completion; visits completed before rates existed use today's rate
            rate = booking.barber_commission_bp
            share = master_share(booking.subtotal, barber_bp if rate is None else rate)
            totals.add(booking, share)
            per_barber.setdefault(booking.barber_id, (barber_name, barber_bp, Totals()))[2].add(
                booking, share
            )
            method = booking.payment_method.value if booking.payment_method else None
            per_method[method][0] += 1
            per_method[method][1] += booking.paid_amount or 0
            if with_rows:
                export_rows.append(
                    {
                        "date": booking.start_at.astimezone(tz).strftime("%Y-%m-%d %H:%M"),
                        "barber": barber_name,
                        "client": client_name or "",
                        "phone": client_phone or "",
                        "subtotal": booking.subtotal,
                        "bonus_spent": booking.bonus_spent,
                        "discount": booking.discount,
                        "total_due": booking.total_due,
                        "paid": booking.paid_amount or 0,
                        "master_share": share,
                        "payment_method": method or "",
                        "booking_id": str(booking.id),
                    }
                )

        ids = [booking.id for booking, *_ in rows]
        by_service: list[tuple[uuid.UUID | None, dict[str, str], int, int]] = []
        if ids:
            service_rows = await self.session.execute(
                select(
                    BookingService.service_id,
                    BookingService.name_snapshot["ru"].astext.label("service_name"),
                    func.count(),
                    func.sum(BookingService.price),
                )
                .where(BookingService.booking_id.in_(ids))
                .group_by(BookingService.service_id, literal_column("service_name"))
                .order_by(func.sum(BookingService.price).desc())
            )
            by_service = [
                (row[0], {"ru": row[1] or ""}, int(row[2]), int(row[3] or 0))
                for row in service_rows.all()
            ]
        daily = await self._daily(branch_id, salon.timezone, date_from, date_to)
        return FinanceReport(
            date_from=date_from,
            date_to=date_to,
            currency=salon.currency,
            totals=totals,
            by_barber=sorted(
                ((bid, name, bp, t) for bid, (name, bp, t) in per_barber.items()),
                key=lambda item: -item[3].paid,
            ),
            by_service=by_service,
            by_method=[(m, c[0], c[1]) for m, c in per_method.items()],
            daily=daily,
            rows=export_rows,
        )


EXPORT_COLUMNS = [
    ("date", "Дата"),
    ("barber", "Мастер"),
    ("client", "Клиент"),
    ("phone", "Телефон"),
    ("subtotal", "Сумма"),
    ("bonus_spent", "Бонусами"),
    ("discount", "Скидка (промокод)"),
    ("total_due", "К оплате"),
    ("paid", "Оплачено"),
    ("master_share", "Мастеру"),
    ("payment_method", "Способ оплаты"),
    ("booking_id", "ID записи"),
]
MONEY_COLUMNS = {"subtotal", "bonus_spent", "discount", "total_due", "paid", "master_share"}


def _major(amount: int) -> str:
    """Minor units → '1500.00' text (exact, no float)."""
    sign = "-" if amount < 0 else ""
    major, minor = divmod(abs(amount), 100)
    return f"{sign}{major}.{minor:02d}"


def export_csv(report: FinanceReport) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([title for _, title in EXPORT_COLUMNS])
    for row in report.rows:
        writer.writerow(
            [_major(row[key]) if key in MONEY_COLUMNS else row[key] for key, _ in EXPORT_COLUMNS]
        )
    # BOM so that Excel opens UTF-8 Cyrillic correctly
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def export_xlsx(report: FinanceReport) -> bytes:
    from decimal import Decimal

    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Визиты"
    sheet.append([title for _, title in EXPORT_COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in report.rows:
        sheet.append(
            [
                Decimal(_major(row[key])) if key in MONEY_COLUMNS else row[key]
                for key, _ in EXPORT_COLUMNS
            ]
        )
    for index, (key, _) in enumerate(EXPORT_COLUMNS, start=1):
        if key in MONEY_COLUMNS:
            for cell in sheet.iter_cols(min_col=index, max_col=index, min_row=2):
                for item in cell:
                    item.number_format = "#,##0.00"
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = (
            38 if key == "booking_id" else 16
        )

    summary = workbook.create_sheet("Мастера")
    summary.append(
        ["Мастер", "Визиты", "Сумма", "Бонусами", "Оплачено", "Процент сейчас", "Мастеру", "Салону"]
    )
    for _, name, commission_bp, totals in report.by_barber:
        summary.append(
            [
                name,
                totals.bookings,
                Decimal(_major(totals.subtotal)),
                Decimal(_major(totals.bonus_spent)),
                Decimal(_major(totals.paid)),
                Decimal(commission_bp) / 100,
                Decimal(_major(totals.master_share)),
                Decimal(_major(totals.paid - totals.master_share)),
            ]
        )
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
