"""tools 테스트가 함께 쓰는 도우미: httpx.AsyncClient 가 실제 네트워크 대신 정한 응답을 받게 한다."""

import httpx
from collections.abc import Callable

Handler = Callable[[httpx.Request], httpx.Response]


def route_httpx(monkeypatch, handler: Handler) -> list[httpx.Request]:  # type: ignore[no-untyped-def]
    """이후 만든 모든 httpx.AsyncClient 의 요청을 handler 로 보낸다. 받은 요청을 순서대로 돌려준다."""
    seen: list[httpx.Request] = []
    transport = httpx.MockTransport(lambda request: seen.append(request) or handler(request))
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return seen
