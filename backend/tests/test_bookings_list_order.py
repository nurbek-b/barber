from __future__ import annotations

import httpx

from tests.test_bookings_admin import (  # noqa: F401 - pytest fixtures
    ADMIN,
    MONDAY,
    World,
    clock,
    create,
    local,
    world,
)


async def test_list_newest_first(
    owner_client: httpx.AsyncClient,
    world: World,  # noqa: F811
    clock: list,  # noqa: F811
) -> None:
    early = await create(owner_client, world, local(MONDAY, 11))
    late = await create(owner_client, world, local(MONDAY, 15))

    default = (await owner_client.get(f"{ADMIN}/bookings")).json()
    assert [b["id"] for b in default["items"]] == [early["id"], late["id"]]

    newest = (await owner_client.get(f"{ADMIN}/bookings", params={"newest_first": True})).json()
    assert [b["id"] for b in newest["items"]] == [late["id"], early["id"]]
    assert newest["total"] == 2
