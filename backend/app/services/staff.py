"""Staff accounts (owner only) and the audit log viewer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.core.security.passwords import hash_password
from app.models import AdminUser, AuditLog, Barber
from app.models.enums import ActorType, AdminRole
from app.repositories.staff import RefreshTokenRepository
from app.schemas.admin import StaffIn, StaffPatch
from app.services.audit import Actor, AuditService, diff, snapshot


class StaffService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)
        self.tokens = RefreshTokenRepository(session)

    async def list_all(self) -> list[AdminUser]:
        rows = await self.session.execute(
            select(AdminUser).order_by(AdminUser.role, AdminUser.login)
        )
        return list(rows.scalars())

    async def _check_barber(
        self, branch_id: uuid.UUID, barber_id: uuid.UUID | None, exclude: uuid.UUID | None = None
    ) -> None:
        if barber_id is None:
            return
        barber = await self.session.get(Barber, barber_id)
        if barber is None or barber.branch_id != branch_id:
            raise ValidationAppError("Barber not found", code="barber_not_found")
        query = select(AdminUser.id).where(AdminUser.barber_id == barber_id)
        if exclude is not None:
            query = query.where(AdminUser.id != exclude)
        if await self.session.scalar(query) is not None:
            raise ConflictError("This barber already has an account", code="barber_has_account")

    async def create(self, branch_id: uuid.UUID, data: StaffIn, actor: Actor) -> AdminUser:
        login = data.login.strip().lower()
        if await self.session.scalar(select(AdminUser.id).where(AdminUser.login == login)):
            raise ConflictError("Login is taken", code="login_taken")
        await self._check_barber(branch_id, data.barber_id)
        account = AdminUser(
            login=login,
            password_hash=hash_password(data.password),
            full_name=data.full_name,
            role=data.role,
            barber_id=data.barber_id,
            language=data.language,
        )
        self.session.add(account)
        await self.session.flush()
        self.audit.record(actor, "staff.create", "admin_user", account.id, after=snapshot(account))
        await self.session.commit()
        return account

    async def update(
        self,
        branch_id: uuid.UUID,
        account_id: uuid.UUID,
        data: StaffPatch,
        actor: Actor,
        now: datetime,
    ) -> AdminUser:
        account = await self.session.get(AdminUser, account_id)
        if account is None:
            raise NotFoundError("Account not found")
        changes = data.model_dump(exclude_unset=True)
        if account.id == actor.id and (
            changes.get("is_active") is False
            or (changes.get("role") not in (None, AdminRole.OWNER))
        ):
            raise ValidationAppError(
                "You cannot disable or demote your own account", code="self_lockout"
            )
        before = snapshot(account)
        role = changes.get("role") or account.role
        barber_id = changes.get("barber_id", account.barber_id)
        if role is AdminRole.BARBER and barber_id is None:
            raise ValidationAppError(
                "Barber accounts must be linked to a barber", code="barber_required"
            )
        if role is not AdminRole.BARBER:
            barber_id = None
        await self._check_barber(branch_id, barber_id, exclude=account.id)
        account.role = role
        account.barber_id = barber_id
        for key in ("full_name", "language", "is_active"):
            if key in changes and changes[key] is not None:
                setattr(account, key, changes[key])
        password_changed = bool(changes.get("password"))
        if password_changed:
            account.password_hash = hash_password(changes["password"])
        await self.session.flush()
        if password_changed or not account.is_active or before["role"] != account.role.value:
            # sign out everywhere: new credentials or permissions must take effect now
            for family in await self._families(account.id):
                await self.tokens.revoke_family(family, now)
        old, new = diff(before, snapshot(account))
        if password_changed:
            new["password"] = "changed"  # noqa: S105 - audit marker, not a secret
        if new:
            self.audit.record(
                actor, "staff.update", "admin_user", account.id, before=old, after=new
            )
        await self.session.commit()
        return account

    async def _families(self, account_id: uuid.UUID) -> list[uuid.UUID]:
        from app.models import AdminRefreshToken

        rows = await self.session.execute(
            select(AdminRefreshToken.family_id)
            .where(AdminRefreshToken.admin_user_id == account_id)
            .distinct()
        )
        return list(rows.scalars())

    # ------------------------------------------------------------------ audit

    async def audit_log(
        self,
        *,
        entity_type: str | None,
        entity_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        action: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[AuditLog, str | None]], int]:
        query = select(AuditLog, AdminUser.login).outerjoin(
            AdminUser,
            (AuditLog.actor_type == ActorType.ADMIN) & (AdminUser.id == AuditLog.actor_id),
        )
        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
        if entity_id:
            query = query.where(AuditLog.entity_id == entity_id)
        if actor_id:
            query = query.where(AuditLog.actor_id == actor_id)
        if action:
            query = query.where(AuditLog.action.startswith(action))
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.execute(
            query.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        )
        return [(row[0], row[1]) for row in rows.all()], int(total or 0)
