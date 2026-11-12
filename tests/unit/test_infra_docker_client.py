"""infra 의 Docker 클라이언트: compose 라벨로 컨테이너를 찾고 통계를 붙이며, 허용 밖 서비스는 부르기 전에 막는다."""

import json
import httpx
import pytest

from jarvis.infra.docker_client import DockerClient

ALLOWED = frozenset({"jarvis-backend"})


def _handler(calls: list[str], fail: bool = False):  # type: ignore[no-untyped-def]
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if fail:
            raise httpx.ConnectError("down")
        if request.url.path == "/containers/json":
            label = json.loads(request.url.params["filters"])["label"][0]
            return httpx.Response(200, json=[{"Id": "abc"}] if label.endswith("=jarvis-backend") else [])
        if request.url.path == "/containers/abc/json":
            return httpx.Response(200, json={"Id": "abc", "State": {"Status": "running"}, "RestartCount": 2})
        if request.url.path == "/containers/abc/stats":
            return httpx.Response(200, json={"memory_stats": {"usage": 100, "limit": 1000}})
        if request.url.path == "/containers/abc/restart":
            return httpx.Response(204)
        return httpx.Response(404)

    return handle


def _client(calls: list[str], fail: bool = False) -> DockerClient:
    transport = httpx.MockTransport(_handler(calls, fail))
    return DockerClient("http://proxy", ALLOWED, client=httpx.AsyncClient(base_url="http://proxy", transport=transport))


async def test_find_reads_state_and_stats():
    calls: list[str] = []
    client = _client(calls)

    state = await client.find("jarvis-backend")
    assert state is not None
    full = await client.with_stats(state)

    assert (full.id, full.status, full.restart_count) == ("abc", "running", 2)
    assert (full.memory_usage, full.memory_limit) == (100, 1000)


async def test_restart_posts_once_and_unknown_service_is_refused_before_any_call():
    calls: list[str] = []
    client = _client(calls)

    assert await client.restart("jarvis-backend") is True
    assert calls.count("POST /containers/abc/restart") == 1
    with pytest.raises(ValueError):
        await client.restart("postgres")
    assert not any("postgres" in c for c in calls)


async def test_proxy_down_means_none_not_an_exception():
    client = _client([], fail=True)
    assert await client.find("jarvis-backend") is None
    assert await client.restart("jarvis-backend") is False
