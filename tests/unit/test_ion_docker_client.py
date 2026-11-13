"""ion 의 Docker 클라이언트: compose 라벨로 컨테이너를 찾고 통계를 붙이며, 허용 밖 서비스는 부르기 전에 막는다."""

import json
import httpx
import pytest

from jarvis.ion.docker_client import DockerClient, demux_logs

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


def _frame(kind: int, payload: bytes) -> bytes:
    return bytes([kind, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload


async def test_logs_demuxes_docker_frames_and_passes_the_window(monkeypatch):
    calls: list[str] = []
    params: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/containers/json":
            return httpx.Response(200, json=[{"Id": "abc"}])
        if request.url.path == "/containers/abc/json":
            return httpx.Response(200, json={"Id": "abc", "State": {"Status": "running"}, "RestartCount": 0})
        if request.url.path == "/containers/abc/logs":
            params.update(dict(request.url.params))
            return httpx.Response(200, content=_frame(1, b"out line\n") + _frame(2, b"err line\n"))
        return httpx.Response(404)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://proxy")
    client = DockerClient("http://proxy", ALLOWED, client=http)
    text = await client.logs("jarvis-backend", 100, 200, 50)
    assert text == "out line\nerr line\n"
    assert params == {"stdout": "true", "stderr": "true", "tail": "50", "since": "100", "until": "200"}


def test_demux_logs_keeps_plain_text_and_broken_frames_as_is():
    assert demux_logs(b"plain tty text\n") == "plain tty text\n"
    assert demux_logs(_frame(1, b"ab") + b"\x01\x00\x00\x00\x00\x00\x00\x09x") == (
        _frame(1, b"ab") + b"\x01\x00\x00\x00\x00\x00\x00\x09x").decode("utf-8", "replace")
    assert demux_logs(b"") == ""
