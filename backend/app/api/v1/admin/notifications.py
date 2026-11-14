from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import Field

from app.api.deps import AdminContext, SessionDep, require
from app.core.errors import ErrorResponse
from app.models.enums import NotificationType
from app.schemas.common import ApiModel
from app.services.notifications import NotificationService
from app.services.permissions import Perm

router = APIRouter(prefix="/notifications", tags=["admin-notifications"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.NOTIFICATIONS_READ))]


class NotificationOut(ApiModel):
    id: uuid.UUID
    type: NotificationType
    booking_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime
    read: bool


class UnreadCountOut(ApiModel):
    unread: int


class ReadAllOut(ApiModel):
    marked: int = Field(description="How many notifications were marked as read")


@router.get("", response_model=list[NotificationOut], responses=ERRORS)
async def feed(
    ctx: CanRead,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before: datetime | None = Query(default=None, description="Paging: older than"),
    since: datetime | None = Query(
        default=None, description="Catch-up after a WebSocket reconnect: newer than"
    ),
    unread_only: bool = False,
) -> list[NotificationOut]:
    items = await NotificationService(session).feed(
        ctx.branch_id, ctx.admin, limit=limit, before=before, since=since, unread_only=unread_only
    )
    return [
        NotificationOut(
            id=item.notification.id,
            type=item.notification.type,
            booking_id=item.notification.booking_id,
            payload=item.notification.payload,
            created_at=item.notification.created_at,
            read=item.read,
        )
        for item in items
    ]


@router.get("/unread-count", response_model=UnreadCountOut, responses=ERRORS)
async def unread_count(ctx: CanRead, session: SessionDep) -> UnreadCountOut:
    return UnreadCountOut(
        unread=await NotificationService(session).unread_count(ctx.branch_id, ctx.admin)
    )


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def mark_read(notification_id: uuid.UUID, ctx: CanRead, session: SessionDep) -> None:
    await NotificationService(session).mark_read(ctx.branch_id, ctx.admin, notification_id)


@router.post("/read-all", response_model=ReadAllOut, responses=ERRORS)
async def mark_all_read(ctx: CanRead, session: SessionDep) -> ReadAllOut:
    return ReadAllOut(
        marked=await NotificationService(session).mark_all_read(ctx.branch_id, ctx.admin)
    )
