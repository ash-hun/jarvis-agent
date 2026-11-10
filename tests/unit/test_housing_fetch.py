"""housing: fetch 의 KST 오늘과 게시판 조회가 연결 오류에만 한 번 다시 보내는지 검증."""

import httpx
import pytest
import functools
from datetime import date

from jarvis.core.tools.housing.fetch import FetchError, fetch_html, kst_today
from jarvis.core.tools.housing import fetch as fetch_mod


def test_kst_today_returns_a_date():
    assert isinstance(kst_today(), date)


def _serve(monkeypatch: pytest.MonkeyPatch, outcomes: list[httpx.Response | Exception]) -> list[int]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", functools.partial(real, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(fetch_mod, "RETRY_DELAY_SEC", 0.0)
    return calls


async def test_fetch_html_retries_once_after_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, [httpx.RemoteProtocolError("Server disconnected"), httpx.Response(200, text="ok")])
    assert await fetch_html("https://apply.lh.or.kr/x", {}) == "ok"
    assert len(calls) == 2


async def test_fetch_html_does_not_retry_error_status(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, [httpx.Response(503), httpx.Response(200, text="ok")])
    with pytest.raises(FetchError, match="503"):
        await fetch_html("https://apply.lh.or.kr/x", {})
    assert len(calls) == 1


async def test_fetch_html_gives_up_after_second_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _serve(monkeypatch, [httpx.ConnectError("refused"), httpx.ConnectError("refused")])
    with pytest.raises(FetchError, match="닿지 못했다"):
        await fetch_html("https://apply.lh.or.kr/x", {})
    assert len(calls) == 2
