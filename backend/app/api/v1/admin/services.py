from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminContext, SessionDep, require
from app.core.errors import ErrorResponse
from app.schemas.catalog import (
    ServiceCategoryIn,
    ServiceCategoryOut,
    ServiceCategoryPatch,
    ServiceIn,
    ServiceOut,
    ServicePatch,
)
from app.schemas.common import Page
from app.services.catalog import CatalogService
from app.services.permissions import Perm

router = APIRouter(tags=["admin-services"])

ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}

CanRead = Annotated[AdminContext, Depends(require(Perm.SERVICES_READ))]
CanWrite = Annotated[AdminContext, Depends(require(Perm.SERVICES_WRITE))]


# ---------- categories ----------


@router.get("/service-categories", response_model=list[ServiceCategoryOut], responses=ERRORS)
async def list_categories(ctx: CanRead, session: SessionDep) -> list[ServiceCategoryOut]:
    items = await CatalogService(session).list_categories(ctx.branch_id)
    return [ServiceCategoryOut.model_validate(item) for item in items]


@router.post(
    "/service-categories",
    response_model=ServiceCategoryOut,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_category(
    body: ServiceCategoryIn, ctx: CanWrite, session: SessionDep
) -> ServiceCategoryOut:
    item = await CatalogService(session).create_category(ctx.branch_id, body, ctx.actor)
    return ServiceCategoryOut.model_validate(item)


@router.patch(
    "/service-categories/{category_id}", response_model=ServiceCategoryOut, responses=ERRORS
)
async def update_category(
    category_id: uuid.UUID, body: ServiceCategoryPatch, ctx: CanWrite, session: SessionDep
) -> ServiceCategoryOut:
    item = await CatalogService(session).update_category(
        ctx.branch_id, category_id, body, ctx.actor
    )
    return ServiceCategoryOut.model_validate(item)


@router.delete(
    "/service-categories/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERRORS,
)
async def delete_category(category_id: uuid.UUID, ctx: CanWrite, session: SessionDep) -> None:
    await CatalogService(session).delete_category(ctx.branch_id, category_id, ctx.actor)


# ---------- services ----------


@router.get("/services", response_model=Page[ServiceOut], responses=ERRORS)
async def list_services(
    ctx: CanRead,
    session: SessionDep,
    only_active: bool = False,
    category_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ServiceOut]:
    items, total = await CatalogService(session).list_services(
        ctx.branch_id,
        only_active=only_active,
        category_id=category_id,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[ServiceOut.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED, responses=ERRORS
)
async def create_service(body: ServiceIn, ctx: CanWrite, session: SessionDep) -> ServiceOut:
    item = await CatalogService(session).create_service(ctx.branch_id, body, ctx.actor)
    return ServiceOut.model_validate(item)


@router.get("/services/{service_id}", response_model=ServiceOut, responses=ERRORS)
async def get_service(service_id: uuid.UUID, ctx: CanRead, session: SessionDep) -> ServiceOut:
    item = await CatalogService(session).get_service(ctx.branch_id, service_id)
    return ServiceOut.model_validate(item)


@router.patch("/services/{service_id}", response_model=ServiceOut, responses=ERRORS)
async def update_service(
    service_id: uuid.UUID, body: ServicePatch, ctx: CanWrite, session: SessionDep
) -> ServiceOut:
    item = await CatalogService(session).update_service(ctx.branch_id, service_id, body, ctx.actor)
    return ServiceOut.model_validate(item)


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS)
async def deactivate_service(service_id: uuid.UUID, ctx: CanWrite, session: SessionDep) -> None:
    await CatalogService(session).deactivate_service(ctx.branch_id, service_id, ctx.actor)
