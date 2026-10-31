"""thought 의 decision model 클라이언트: System One API 의 noul, choice 응답을 읽고 실패는 None 으로 알린다."""

import json
import httpx
import pytest

from jarvis.model_layer import decision as decision_mod
from jarvis.model_layer.decision import DecisionModel

CRITERIA = {"direct": "바로 답한다", "think": "따져 본다"}


def _serve(monkeypatch, handler) -> list[dict]:
    """httpx 를 가짜 전송으로 바꾸고 보낸 요청 본문을 모은다."""
    sent: list[dict] = []
    real_client = httpx.AsyncClient

    def recording(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return handler(request)

    def fake_client(**kwargs):
        return real_client(transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr(decision_mod.httpx, "AsyncClient", fake_client)
    return sent


async def test_choice_probabilities_sends_choice_question(monkeypatch):
    answer = {"type": "choice", "choice": "think", "probabilities": {"direct": 0.3, "think": 0.7}}
    sent = _serve(monkeypatch, lambda r: httpx.Response(200, json={"answers": {"q": answer}}))

    got = await DecisionModel("router", "http://router:11435/").choice_probabilities("요청", "질문", CRITERIA)

    assert got == {"direct": 0.3, "think": 0.7}
    question = {"type": "choice", "instructions": "질문", "criteria": CRITERIA}
    assert sent == [{"model": "router", "state": "요청", "questions": {"q": question}}]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"detail": "boom"}),
        httpx.Response(200, json={"answers": {"q": {"probabilities": {"think": 0.7}}}}),  # 선택지가 빠짐
        httpx.Response(200, json={"oops": True}),
    ],
)
async def test_choice_probabilities_returns_none_on_bad_answer(monkeypatch, response):
    _serve(monkeypatch, lambda r: response)

    assert await DecisionModel("router", "http://router:11435").choice_probabilities("요청", "질문", CRITERIA) is None


async def test_yes_probability_reads_noul(monkeypatch):
    sent = _serve(monkeypatch, lambda r: httpx.Response(200, json={"answers": {"q": {"noul": 0.8}}}))
    p = await DecisionModel("tev1", "http://ollama:11434").yes_probability({"now": "x"}, "말할까", "아니", "응")

    assert p == 0.8
    assert sent[0]["questions"]["q"]["criteria"] == {"false": "아니", "true": "응"}
