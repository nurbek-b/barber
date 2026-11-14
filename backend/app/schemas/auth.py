from __future__ import annotations

import uuid

from pydantic import Field

from app.models.enums import AdminRole
from app.schemas.common import ApiModel


class LoginRequest(ApiModel):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class AdminMe(ApiModel):
    id: uuid.UUID
    login: str
    full_name: str
    role: AdminRole
    branch_id: uuid.UUID | None
    barber_id: uuid.UUID | None
    language: str
    permissions: list[str]


class LoginResponse(ApiModel):
    user: AdminMe
    csrf_token: str = Field(description="Also set as a readable cookie; send in X-CSRF-Token")


class RefreshResponse(ApiModel):
    csrf_token: str


class WsTicketResponse(ApiModel):
    ticket: str
    expires_in: int
