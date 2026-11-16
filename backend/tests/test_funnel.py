"""Booking funnel: anonymous step events, deduplicated per session, report per source."""

from __future__ import annotations

from datetime import date

import httpx

from app.models import Branch

PUBLIC = "/api/v1/public"
ADMIN = "/api/v1/admin"


async def _event(http: httpx.AsyncClient, session: str, step: str, source: str = "web") -> int:
    response = await http.post(
        f"{PUBLIC}/events", json={"session_id": session, "source": source, "step": step}
    )
    return response.status_code


async def test_funnel_report(
    client: httpx.AsyncClient, owner_client: httpx.AsyncClient, branch: Branch
) -> None:
    for session, steps in {
        "session-aaaa": ["open", "barber", "services", "time", "confirm", "booked"],
        "session-bbbb": ["open", "barber", "barber", "services"],  # a repeat is ignored
        "session-cccc": ["open"],
    }.items():
        for step in steps:
            assert await _event(client, session, step) == 204
    assert await _event(client, "session-dddd", "open", source="miniapp") == 204
    assert await _event(client, "bad id!", "open") == 422
    assert await _event(client, "session-eeee", "paid") == 422

    today = date.today().isoformat()
    report = (
        await owner_client.get(
            f"{ADMIN}/reports/funnel", params={"date_from": today, "date_to": today}
        )
    ).json()
    web = next(item for item in report if item["source"] == "web")
    counts = {step["step"]: (step["sessions"], step["rate"]) for step in web["steps"]}
    assert counts["open"] == (3, 1.0)
    assert counts["barber"] == (2, 0.6667)
    assert counts["booked"] == (1, 0.3333)
    mini = next(item for item in report if item["source"] == "miniapp")
    assert mini["steps"][0]["sessions"] == 1
