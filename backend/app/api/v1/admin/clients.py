from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import AdminContext, NowDep, SessionDep, require
from app.core.errors import ErrorResponse
from app.models import Client
from app.schemas.admin import BlockIn, ClientCard, ClientIn, ClientPage, ClientPatch, ClientRow
from app.services.clients_admin import ClientAdminService, ClientListItem, SortField
from app.services.permissions import Perm

router = APIRouter(prefix="/clients", tags=["admin-clients"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.CLIENTS_READ))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.CLIENTS_WRITE))]


def to_row(item: ClientListItem) -> ClientRow:
    client = item.client
    return ClientRow(
        id=client.id,
        name=client.name,
        phone=client.phone,
        telegram_username=item.username,
        language=client.language,
        tags=list(client.tags or []),
        is_blocked=client.is_blocked,
        level_id=client.level_id,
        bonus_balance=client.bonus_balance,
        total_spent=client.total_spent,
        visits_count=client.visits_count,
        no_show_count=client.no_show_count,
        last_visit_at=item.last_visit_at,
        created_at=client.created_at,
    )


def to_card(item: ClientListItem, upcoming: int) -> ClientCard:
    client = item.client
    return ClientCard(
        **to_row(item).model_dump(),
        birthday=client.birthday,
        notes=client.notes,
        referral_code=client.referral_code,
        referred_by_client_id=client.referred_by_client_id,
        upcoming_count=upcoming,
        average_check=client.total_spent // client.visits_count if client.visits_count else 0,
    )


async def _card(
    service: ClientAdminService, ctx: AdminContext, client: Client, now: NowDep
) -> ClientCard:
    details = await service.card(ctx.branch_id, client.id, now)
    return to_card(details.item, details.upcoming_count)


@router.get("", response_model=ClientPage, responses=ERRORS)
async def list_clients(
    ctx: CanRead,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=100, description="Name, @username or phone")] = None,
    tag: str | None = None,
    blocked: bool | None = None,
    level_id: uuid.UUID | None = None,
    sort: SortField = "created_at",
    desc: bool = True,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClientPage:
    items, total = await ClientAdminService(session).search(
        ctx.branch_id,
        q=q,
        tag=tag,
        blocked=blocked,
        level_id=level_id,
        sort=sort,
        descending=desc,
        limit=limit,
        offset=offset,
    )
    return ClientPage(items=[to_row(i) for i in items], total=total, limit=limit, offset=offset)


@router.post("", response_model=ClientCard, status_code=201, responses=ERRORS)
async def create_client(
    body: ClientIn, ctx: CanWrite, session: SessionDep, now: NowDep
) -> ClientCard:
    service = ClientAdminService(session)
    client = await service.create(ctx.branch_id, body, ctx.actor)
    return await _card(service, ctx, client, now)


@router.get("/{client_id}", response_model=ClientCard, responses=ERRORS)
async def get_client(
    client_id: uuid.UUID, ctx: CanRead, session: SessionDep, now: NowDep
) -> ClientCard:
    details = await ClientAdminService(session).card(ctx.branch_id, client_id, now)
    return to_card(details.item, details.upcoming_count)


@router.patch("/{client_id}", response_model=ClientCard, responses=ERRORS)
async def update_client(
    client_id: uuid.UUID, body: ClientPatch, ctx: CanWrite, session: SessionDep, now: NowDep
) -> ClientCard:
    service = ClientAdminService(session)
    client = await service.update(ctx.branch_id, client_id, body, ctx.actor)
    return await _card(service, ctx, client, now)


@router.post("/{client_id}/block", response_model=ClientCard, responses=ERRORS)
async def block_client(
    client_id: uuid.UUID, body: BlockIn, ctx: CanWrite, session: SessionDep, now: NowDep
) -> ClientCard:
    """Blocking is manual only: a blocked client can't use the Mini App or book online."""
    service = ClientAdminService(session)
    client = await service.set_blocked(
        ctx.branch_id, client_id, body.blocked, body.reason, ctx.actor
    )
    return await _card(service, ctx, client, now)
