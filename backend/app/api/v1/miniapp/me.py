from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import MiniappContext, MiniappDep, SessionDep, SettingsDep
from app.core.errors import ErrorResponse, ValidationAppError
from app.schemas.miniapp import ClientMe, ClientMePatch, PhoneIn
from app.services.audit import AuditService, diff, snapshot
from app.services.miniapp_auth import MiniappAuthService

router = APIRouter(prefix="/me", tags=["miniapp-me"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


def to_me(ctx: MiniappContext) -> ClientMe:
    client = ctx.identity.client
    return ClientMe(
        id=client.id,
        telegram_id=ctx.identity.user.telegram_id,
        name=client.name,
        phone=client.phone,
        birthday=client.birthday,
        language=client.language,
        bonus_balance=client.bonus_balance,
        referral_code=client.referral_code,
        is_new=ctx.identity.is_new,
    )


@router.get("", response_model=ClientMe, responses=ERRORS)
async def get_me(ctx: MiniappDep) -> ClientMe:
    """Returns the client profile; the first call registers the client."""
    return to_me(ctx)


@router.patch("", response_model=ClientMe, responses=ERRORS)
async def update_me(body: ClientMePatch, ctx: MiniappDep, session: SessionDep) -> ClientMe:
    client = ctx.identity.client
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if (
        "birthday" in changes
        and client.birthday is not None
        and changes["birthday"] != client.birthday
    ):
        # Protects the birthday bonus from abuse; staff can still change it.
        raise ValidationAppError(
            "Birthday can be changed only by the salon", code="birthday_locked"
        )
    before = snapshot(client)
    for key, value in changes.items():
        setattr(client, key, value)
    await session.flush()
    old, new = diff(before, snapshot(client))
    if new:
        AuditService(session).record(
            ctx.actor, "client.update", "client", client.id, before=old, after=new
        )
    await session.commit()
    return to_me(ctx)


@router.post("/phone", response_model=ClientMe, responses=ERRORS)
async def save_phone(
    body: PhoneIn, ctx: MiniappDep, session: SessionDep, settings: SettingsDep
) -> ClientMe:
    """Accepts the signed contact returned by Telegram's requestContact()."""
    await MiniappAuthService(session, settings).save_phone(ctx.identity, body.contact)
    return to_me(ctx)
