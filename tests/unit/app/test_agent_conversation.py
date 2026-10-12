"""ask_agent: 받을 수 있는 질문의 규칙, 쌍마다 이어지는 대화 세션, 깊이 제한, 바쁨과 백그라운드 답 처리."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.app.agent_conversation import (
    MAX_PEER_HOPS,
    PEER_REQUEST_RULE,
    AskAgentTool,
    ask,
    peer_chain,
    peer_session_id,
    refusal,
)
from jarvis.core.session import SessionBusy
from jarvis.core.tools.registry import ToolContext
from jarvis.memory.scope import MemoryScope
from jarvis.model_layer.types import AssistantMessage, TextContent, Usage

IDS = ["main", "karen"]


def _reply(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], provider="p", model="m", usage=Usage())


def _agents():
    profiles = {
        "main": SimpleNamespace(agent_id="main", name="J.A.R.V.I.S.", is_main=True, description=""),
        "karen": SimpleNamespace(agent_id="karen", name="K.A.R.E.N.", is_main=False, description="정보 수집"),
    }
    return SimpleNamespace(ids=lambda: IDS, profiles=lambda: list(profiles.values()), get=profiles.get)


def _context(agent_id: str = "main", session_id: str = "default") -> ToolContext:
    return ToolContext(scope=MemoryScope(user_id="u", agent_id=agent_id, session_id=session_id), session_id=session_id)


def test_peer_session_id_is_per_ordered_pair():
    assert peer_session_id("main", "karen") == "peer-main-karen"
    assert peer_session_id("karen", "main") == "peer-karen-main"


@pytest.mark.parametrize(
    ("chain", "caller", "target", "message", "ok"),
    [
        (("main",), "main", "karen", "뉴스", True),
        (("main", "karen"), "karen", "main", "관심 분야?", True),  # 되묻기 한 번은 된다
        (("main", "karen", "main"), "main", "karen", "또", False),  # 그 이상은 끊는다
        (("main",), "main", "main", "나에게", False),
        (("main",), "main", "ghost", "누구", False),
        (("main",), "main", "karen", "", False),
    ],
)
def test_refusal_rules(chain, caller, target, message, ok):
    assert (refusal(IDS, chain, caller, target, message) is None) is ok
    assert MAX_PEER_HOPS == 3


async def test_tool_opens_pair_session_and_returns_named_reply():
    session = MagicMock()
    session.prompt = AsyncMock(return_value=_reply("뉴스 셋"))
    opener = AsyncMock(return_value=session)
    tool = AskAgentTool(_agents(), opener)

    result = await tool.execute("c1", {"agent": "karen", "message": "뉴스 찾아 줘"}, context=_context())

    opener.assert_awaited_once_with("karen", "peer-main-karen", "default")
    session.prompt.assert_awaited_once_with(f"[J.A.R.V.I.S. 의 요청] 뉴스 찾아 줘\n({PEER_REQUEST_RULE})")
    assert not result.is_error
    assert result.content[0].text == "[K.A.R.E.N. 의 답]\n뉴스 셋"
    assert peer_chain.get() == ()  # 끝나면 되돌린다


async def test_tool_passes_chain_to_receiver_and_refuses_too_deep():
    seen = []

    async def prompt(text):
        seen.append(peer_chain.get())
        return _reply("ok")

    session = MagicMock()
    session.prompt = prompt
    tool = AskAgentTool(_agents(), AsyncMock(return_value=session))
    await tool.execute("c1", {"agent": "karen", "message": "x"}, context=_context())
    assert seen == [("main", "karen")]

    token = peer_chain.set(("main", "karen", "main"))
    try:
        result = await tool.execute("c2", {"agent": "karen", "message": "x"}, context=_context())
    finally:
        peer_chain.reset(token)
    assert result.is_error and "너무 깊다" in result.content[0].text


async def test_busy_receiver_is_an_error_result():
    session = MagicMock()
    session.prompt = AsyncMock(side_effect=SessionBusy("busy"))
    tool = AskAgentTool(_agents(), AsyncMock(return_value=session))
    result = await tool.execute("c1", {"agent": "karen", "message": "x"}, context=_context())
    assert result.is_error and "다른 일" in result.content[0].text


async def test_ask_waits_for_background_answer_and_reads_history():
    """Dual-Channel 로 백그라운드 답을 하면 prompt 가 None 이다. 끝나길 기다려 저장된 마지막 답을 읽는다."""
    class _Background:
        _session_id = "peer-karen-main"
        _session_repo = SimpleNamespace(get_messages=AsyncMock(return_value=[_reply("나중 답")]))
        prompt = AsyncMock(return_value=None)

        def __init__(self):
            self._states = iter([True, True, False])

        @property
        def is_running(self):
            return next(self._states)

    assert await asyncio.wait_for(ask(_Background(), "q"), 2) == "나중 답"


def test_description_lists_team_and_enum_ids():
    tool = AskAgentTool(_agents(), AsyncMock())
    assert "karen: K.A.R.E.N.: 정보 수집" in tool.description
    assert "main: J.A.R.V.I.S. (팀 총괄)" in tool.description
    assert tool.parameters["properties"]["agent"]["enum"] == IDS


def test_bouncing_received_task_back_is_refused():
    received = "AI 반도체 분야 키워드 3개를 수집해 요약해 줘"
    # KAREN 이 JARVIS 에게 받은 일을 거의 그대로 JARVIS 에게 되돌린다
    assert "되돌릴 수 없다" in refusal(IDS, ("main", "karen"), "karen", "main", received + ".", received)
    # 받은 일과 다른 되묻기는 된다
    assert refusal(IDS, ("main", "karen"), "karen", "main", "사용자가 관심 있는 분야가 뭐야?", received) is None


async def test_receiver_sees_the_request_it_got():
    seen = []

    async def prompt(text):
        from jarvis.app.agent_conversation import peer_request

        seen.append(peer_request.get())
        return _reply("ok")

    session = MagicMock()
    session.prompt = prompt
    tool = AskAgentTool(_agents(), AsyncMock(return_value=session))
    await tool.execute("c1", {"agent": "karen", "message": "뉴스 찾아 줘"}, context=_context())
    assert seen == ["뉴스 찾아 줘"]
