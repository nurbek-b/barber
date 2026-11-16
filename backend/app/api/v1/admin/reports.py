from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import AdminContext, NowDep, SessionDep, require
from app.core.errors import ErrorResponse, ValidationAppError
from app.schemas.admin import (
    DashboardOut,
    FinanceByBarber,
    FinanceByMethod,
    FinanceByService,
    FinanceReportOut,
    FinanceTotals,
    FunnelOut,
    FunnelStepOut,
    RevenuePoint,
)
from app.services.funnel import STEPS, FunnelService
from app.services.permissions import Perm
from app.services.reports import FinanceReport, ReportService, export_csv, export_xlsx

router = APIRouter(tags=["admin-reports"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanDashboard = Annotated[AdminContext, Depends(require(Perm.DASHBOARD_READ))]
CanFinance = Annotated[AdminContext, Depends(require(Perm.FINANCE_READ))]
CanExport = Annotated[AdminContext, Depends(require(Perm.FINANCE_EXPORT))]
MAX_RANGE = timedelta(days=366)


@router.get("/dashboard", response_model=DashboardOut, responses=ERRORS)
async def dashboard(ctx: CanDashboard, session: SessionDep, now: NowDep) -> DashboardOut:
    return DashboardOut.model_validate(await ReportService(session).dashboard(ctx.branch_id, now))


def _check_range(date_from: date, date_to: date) -> None:
    if date_to < date_from or date_to - date_from > MAX_RANGE:
        raise ValidationAppError("Range must be up to one year", code="invalid_date_range")


def to_out(report: FinanceReport) -> FinanceReportOut:
    def totals(t: object) -> FinanceTotals:
        return FinanceTotals.model_validate(t, from_attributes=True)

    return FinanceReportOut(
        date_from=report.date_from,
        date_to=report.date_to,
        currency=report.currency,
        totals=totals(report.totals),
        by_barber=[
            FinanceByBarber(barber_id=bid, name=name, commission_bp=bp, **totals(t).model_dump())
            for bid, name, bp, t in report.by_barber
        ],
        by_service=[
            FinanceByService(service_id=sid, name_i18n=name, count=count, revenue=revenue)
            for sid, name, count, revenue in report.by_service
        ],
        by_payment_method=[
            FinanceByMethod(payment_method=method, bookings=count, paid=paid)
            for method, count, paid in report.by_method
        ],
        daily=[RevenuePoint(date=d, revenue=r, bookings=c) for d, r, c in report.daily],
    )


@router.get("/finance/report", response_model=FinanceReportOut, responses=ERRORS)
async def finance_report(
    ctx: CanFinance,
    session: SessionDep,
    date_from: date,
    date_to: date,
    barber_id: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> FinanceReportOut:
    """Completed visits in [date_from, date_to] (local dates): totals, per barber/service."""
    _check_range(date_from, date_to)
    return to_out(
        await ReportService(session).finance(ctx.branch_id, date_from, date_to, barber_id)
    )


@router.get(
    "/finance/export",
    responses={
        **ERRORS,
        200: {
            "content": {
                "text/csv": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            }
        },
    },
)
async def finance_export(
    ctx: CanExport,
    session: SessionDep,
    date_from: date,
    date_to: date,
    format: Literal["csv", "xlsx"] = "xlsx",
    barber_id: Annotated[list[uuid.UUID] | None, Query()] = None,
) -> Response:
    _check_range(date_from, date_to)
    report = await ReportService(session).finance(
        ctx.branch_id, date_from, date_to, barber_id, with_rows=True
    )
    name = f"finance_{date_from.isoformat()}_{date_to.isoformat()}.{format}"
    if format == "csv":
        content, media = export_csv(report), "text/csv; charset=utf-8"
    else:
        content = export_xlsx(report)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/reports/funnel", response_model=list[FunnelOut], responses=ERRORS)
async def funnel(
    ctx: CanFinance, session: SessionDep, date_from: date, date_to: date
) -> list[FunnelOut]:
    """Booking funnel per source: sessions reaching each step and the share of opens."""
    data = await FunnelService(session).report(ctx.branch_id, date_from, date_to)
    result = []
    for source, counts in data.items():
        opened = counts.get("open", 0)
        result.append(
            FunnelOut(
                source=source,
                steps=[
                    FunnelStepOut(
                        step=step,
                        sessions=counts.get(step, 0),
                        rate=round(counts.get(step, 0) / opened, 4) if opened else 0.0,
                    )
                    for step in STEPS
                ],
            )
        )
    return result
