"""infra 의 백엔드 클라이언트: 건강은 200 만 참이고, 연결 실패는 예외 없이 거짓이나 None 이다."""

import httpx

from jarvis.infra.backend_client import BackendClient


def _client(handler) -> tuple[BackendClient, list[httpx.Request]]:  # type: ignore[no-untyped-def]
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    headers = {"Authorization": "Bearer k"}
    http = httpx.AsyncClient(base_url="http://b", transport=httpx.MockTransport(handle), headers=headers)
    return BackendClient("http://b", "k", client=http), seen


async def test_health_metrics_jobs_and_toggle_go_through_with_the_key():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/api/platform/metrics":
            return httpx.Response(200, json={"agents": []})
        if request.url.path == "/api/jobs":
            return httpx.Response(200, json={"jobs": [{"name": "goal-1", "agent": "karen", "enabled": True}]})
        if request.url.path == "/api/schedules/goal-1":
            return httpx.Response(200, json={"name": "goal-1", "enabled": False})
        return httpx.Response(404)

    client, seen = _client(handle)
    assert await client.health() is True
    assert await client.metrics() == {"agents": []}
    assert [j["name"] for j in await client.jobs()] == ["goal-1"]
    assert await client.set_task_enabled("goal-1", False) is True
    assert all(r.headers["authorization"] == "Bearer k" for r in seen)


async def test_backend_down_is_false_or_none():
    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client, _ = _client(handle)
    assert await client.health() is False
    assert await client.metrics() is None and await client.jobs() == []
    assert await client.set_task_enabled("x", False) is False
