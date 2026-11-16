"""Cloud Run specifics: no shared caching of API answers, GCS-backed media route, HTTP worker."""

from __future__ import annotations

from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient

from app.core import media
from app.core.config import Settings
from app.main import create_app
from app.worker import service as worker_service


async def test_api_responses_are_private(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.headers["cache-control"] == "private, no-store"


class MemoryStorage:
    def __init__(self) -> None:
        self.items: dict[str, bytes] = {"barbers/abc-1.png": b"\x89PNG"}

    async def save(self, key: str, content: bytes) -> None:
        self.items[key] = content

    async def delete(self, key: str) -> None:
        self.items.pop(key, None)

    async def load(self, key: str) -> bytes | None:
        return self.items.get(key)


async def test_gcs_media_route(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = MemoryStorage()
    monkeypatch.setattr("app.main.get_media_storage", lambda _settings: storage)
    gcs = settings.model_copy(update={"media_backend": "gcs", "media_bucket": "b"})
    app = create_app(gcs, redis=FakeAsyncRedis(decode_responses=True))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://t") as http:
        ok = await http.get("/media/barbers/abc-1.png")
        missing = await http.get("/media/barbers/none-1.png")
    assert ok.status_code == 200
    assert ok.content == b"\x89PNG"
    assert ok.headers["content-type"] == "image/png"
    assert "immutable" in ok.headers["cache-control"]
    assert missing.status_code == 404


async def test_local_storage_rejects_traversal(tmp_path: Any) -> None:
    storage = media.LocalMediaStorage(str(tmp_path))
    await storage.save("barbers/x-1.jpg", b"data")
    assert await storage.load("barbers/x-1.jpg") == b"data"
    assert await storage.load("../etc/passwd") is None
    with pytest.raises(ValueError, match="bad media key"):
        await storage.save("barbers/../../x.jpg", b"")


async def test_worker_http_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def outbox(_ctx: dict[str, Any]) -> int:
        calls.append("outbox")
        return 2

    async def reminders(_ctx: dict[str, Any]) -> int:
        calls.append("reminders")
        return 1

    async def bonus(_ctx: dict[str, Any]) -> dict[str, int]:
        return {"burned": 0}

    monkeypatch.setattr(worker_service, "send_outbox", outbox)
    monkeypatch.setattr(worker_service, "queue_reminders", reminders)
    monkeypatch.setattr(worker_service, "bonus_jobs", bonus)
    monkeypatch.setenv("TASKS_TOKEN", "s3cret")
    app = worker_service.create_worker_app(ctx={})
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://w") as http,
    ):
        assert (await http.post("/tasks/tick")).status_code == 401
        tick = await http.post("/tasks/tick", headers={"X-Tasks-Token": "s3cret"})
        bonus_resp = await http.post("/tasks/bonus", headers={"X-Tasks-Token": "s3cret"})
        live = await http.get("/api/v1/health/live")
    assert tick.json() == {"ok": True, "sent": 4, "reminders": 1}
    assert calls == ["outbox", "reminders", "outbox"]
    assert bonus_resp.json() == {"ok": True, "burned": 0}
    assert live.status_code == 200


def test_logs_carry_google_cloud_fields() -> None:
    from app.core.logging import google_cloud_fields

    info = google_cloud_fields(None, "info", {"event": "request", "level": "info"})
    assert info["severity"] == "INFO"
    assert info["message"] == "request"
    assert "@type" not in info

    error = google_cloud_fields(
        None,
        "error",
        {"event": "boom", "level": "error", "exception": "Traceback (most recent call last):\n  x"},
    )
    assert error["severity"] == "ERROR"
    assert error["@type"].endswith("ReportedErrorEvent")
    assert error["stack_trace"].startswith("Traceback")
    assert error["message"].startswith("boom\nTraceback")
