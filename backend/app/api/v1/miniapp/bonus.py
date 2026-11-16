from __future__ import annotations

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from app.api.deps import MiniappDep, NowDep, SessionDep, SettingsDep
from app.api.v1.bonus_views import decode_tx_cursor, encode_tx_cursor, level_out, tx_out
from app.core.errors import ErrorResponse
from app.schemas.bonus import BonusSummaryOut, ExpiringOut, ReferralOut, TransactionPage
from app.schemas.vouchers import MySubscriptionOut
from app.services.bonus import BonusService
from app.services.branches import BranchService
from app.services.miniapp_auth import REFERRAL_PREFIX
from app.services.vouchers import VoucherService, subscription_state

router = APIRouter(tags=["miniapp-bonus"])

ERRORS: dict[int | str, dict[str, object]] = {401: {"model": ErrorResponse}}


@router.get("/bonus", response_model=BonusSummaryOut, responses=ERRORS)
async def bonus_summary(ctx: MiniappDep, session: SessionDep, now: NowDep) -> BonusSummaryOut:
    """Balance, level, progress to the next level and bonuses expiring soon."""
    service = BonusService(session)
    summary = await service.summary(ctx.identity.client, now)
    settings = await service.settings(ctx.branch_id)
    return BonusSummaryOut(
        enabled=summary.enabled,
        balance=summary.balance,
        level=level_out(summary.level),
        next_level=level_out(summary.next_level),
        visits_left=summary.visits_left,
        spent_left=summary.spent_left,
        level_rule=settings.level_rule,
        cashback_bp=summary.cashback_bp,
        max_spend_bp=summary.max_spend_bp,
        expiring=[ExpiringOut(amount=a, expires_at=when) for a, when in summary.expiring],
    )


@router.get("/bonus/transactions", response_model=TransactionPage, responses=ERRORS)
async def bonus_history(
    ctx: MiniappDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: str | None = None,
) -> TransactionPage:
    items = await BonusService(session).history(ctx.client_id, limit + 1, decode_tx_cursor(cursor))
    has_more = len(items) > limit
    items = items[:limit]
    return TransactionPage(
        items=[tx_out(item) for item in items],
        next_cursor=encode_tx_cursor(items[-1]) if has_more and items else None,
    )


@router.get("/referral", response_model=ReferralOut, responses=ERRORS)
async def referral(ctx: MiniappDep, session: SessionDep, settings: SettingsDep) -> ReferralOut:
    """Share links: the Mini App deep link (startapp) and the bot deep link (/start)."""
    service = BonusService(session)
    client = ctx.identity.client
    invited, rewarded = await service.referral_stats(client)
    bonus = await service.settings(ctx.branch_id)
    payload = f"{REFERRAL_PREFIX}{client.referral_code}"
    bot = settings.bot_username or "bot"
    return ReferralOut(
        code=client.referral_code,
        miniapp_link=f"https://t.me/{bot}/{settings.miniapp_short_name}?startapp={payload}",
        bot_link=f"https://t.me/{bot}?start={payload}",
        invited=invited,
        rewarded=rewarded,
        referrer_amount=bonus.referrer_amount,
        referee_amount=bonus.referee_amount,
        enabled=bonus.enabled and bonus.referral_enabled,
    )


@router.get("/subscriptions", response_model=list[MySubscriptionOut], responses=ERRORS)
async def my_subscriptions(
    ctx: MiniappDep, session: SessionDep, now: NowDep
) -> list[MySubscriptionOut]:
    """The client's subscriptions (visits left), newest first."""
    salon = await BranchService(session).settings(ctx.branch_id)
    today = now.astimezone(ZoneInfo(salon.timezone)).date()
    rows = await VoucherService(session).client_subscriptions(
        ctx.branch_id, ctx.identity.client.id, limit=20
    )
    return [
        MySubscriptionOut(
            id=sub.id,
            name=sub.name,
            visits_total=sub.visits_total,
            visits_left=sub.visits_left,
            expires_on=sub.expires_on,
            state=subscription_state(sub, today),
        )
        for sub, _ in rows
    ]
