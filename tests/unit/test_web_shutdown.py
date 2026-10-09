"""Web HUD 세션 종료 훅. save_all_sessions 가 session_repo 이력을 요약해 각 세션 범위로 저장한다."""

from unittest.mock import MagicMock

import pytest

from jarvis.memory import MemoryScope
from jarvis.memory.manager import MemoryManager
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.model_layer.types import UserMessage
from jarvis.ui.web.server import SessionManager


class _Repo:
    def __init__(self, histories: dict[str, list] | None = None, fail_on: set[str] | None = None) -> None:
        self._h = histories or {}
        self._fail = fail_on or set()

    async def get_messages(self, session_id: str) -> list:
        if session_id in self._fail:
            raise RuntimeError("repo unavailable")
        return list(self._h.get(session_id, []))


def _make_manager(sessions: dict) -> SessionManager:
    mgr = SessionManager.__new__(SessionManager)
    mgr._ctx = MagicMock()
    mgr._base_extra = {}
    mgr._sessions = sessions
    mgr._sandboxes = {}
    return mgr


def _mock_session(session_id: str) -> MagicMock:
    s = MagicMock()
    s._session_id = session_id
    s.memory_scope = MemoryScope(user_id="local", session_id=session_id)
    return s


def _user_msg(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


@pytest.mark.asyncio
async def test_save_all_stores_episodic(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())
    model = faux_model_with_response("세션 요약: 사용자가 Python을 배웠습니다.")
    repo = _Repo({"sess1": [_user_msg("Python 배우고 싶어")]})

    await _make_manager({"sess1": _mock_session("sess1")}).save_all_sessions(repo, ltm, model)

    recent = await ltm.recent()
    assert len(recent) == 1
    assert recent[0].session_id == "sess1"
    assert recent[0].source == "session_end"


@pytest.mark.asyncio
async def test_save_all_multiple_sessions(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())
    model = faux_model_with_response("요약")
    repo = _Repo({"a": [_user_msg("메시지 A")], "b": [_user_msg("메시지 B")]})

    await _make_manager({"a": _mock_session("a"), "b": _mock_session("b")}).save_all_sessions(repo, ltm, model)

    assert {e.session_id for e in await ltm.recent()} == {"a", "b"}


@pytest.mark.asyncio
async def test_save_all_skips_empty_sessions(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())
    model = faux_model_with_response("요약")
    await _make_manager({"empty": _mock_session("empty")}).save_all_sessions(_Repo(), ltm, model)
    assert await ltm.recent() == []


@pytest.mark.asyncio
async def test_save_all_no_sessions_does_nothing(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())
    await _make_manager({}).save_all_sessions(_Repo(), ltm, faux_model_with_response("요약"))
    assert await ltm.recent() == []


@pytest.mark.asyncio
async def test_save_all_failure_is_non_fatal():
    ltm = MemoryManager(InMemoryItemStore())
    await _make_manager({"crash": _mock_session("crash")}).save_all_sessions(_Repo(fail_on={"crash"}), ltm, MagicMock())
    assert await ltm.recent() == []


@pytest.mark.asyncio
async def test_save_all_partial_failure_continues(faux_model_with_response):
    ltm = MemoryManager(InMemoryItemStore())
    model = faux_model_with_response("요약")
    repo = _Repo({"ok": [_user_msg("정상 메시지")]}, fail_on={"crash"})
    sessions = {"crash": _mock_session("crash"), "ok": _mock_session("ok")}

    await _make_manager(sessions).save_all_sessions(repo, ltm, model)

    recent = await ltm.recent()
    assert len(recent) == 1 and recent[0].session_id == "ok"


@pytest.mark.asyncio
async def test_summary_lands_in_the_sessions_own_scope(faux_model_with_response):
    """인증된 사용자의 세션 요약은 그 사용자 범위에 private 으로 남아 다른 사용자에게 안 보인다."""
    ltm = MemoryManager(InMemoryItemStore())
    model = faux_model_with_response("jh 의 세션 요약")
    session = _mock_session("s")
    session.memory_scope = MemoryScope(user_id="jh", session_id="s")

    await _make_manager({"s": session}).save_all_sessions(_Repo({"s": [_user_msg("hi")]}), ltm, model)

    assert len(await ltm.recent(scope=MemoryScope(user_id="jh"))) == 1
    assert await ltm.recent(scope=MemoryScope(user_id="other")) == []


@pytest.mark.asyncio
async def test_shutdown_consolidates_facts_from_the_session_summary(faux_model_with_response):
    """종료 시 요약 → 의미 추출 → shared 사실. 요약 모델과 추출 모델이 같은 faux 라 JSON 을 요약으로 쓴다."""
    from jarvis.memory.consolidation.semantic_extract import Fact

    async def extractor(summary: str) -> list[Fact]:
        return [Fact("거주지", "부산", 0.9)]

    ltm = MemoryManager(InMemoryItemStore(), extractor=extractor)
    model = faux_model_with_response("세션 요약: 부산으로 이사했다")
    session = _mock_session("s")
    session.memory_scope = MemoryScope(user_id="jh", session_id="s")

    await _make_manager({"s": session}).save_all_sessions(_Repo({"s": [_user_msg("부산으로 이사했어")]}), ltm, model)

    facts = await ltm.recent(scope=MemoryScope(user_id="jh", agent_id="researcher"))  # shared 라 서브 에이전트도 본다
    assert [f.content for f in facts] == ["거주지: 부산"]
