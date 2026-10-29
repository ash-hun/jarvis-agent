"""Web HUD 세션 종료 훅. save_all_sessions 가 session_repo 이력을 요약해 각 세션 범위로 저장한다."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from jarvis.ui.web.session_registry import SessionRegistry, last_conversation
from jarvis.agent_layer.session.protocol import SessionMetadata
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.memory_service import MemoryService
from jarvis.model_layer.types import UserMessage
from jarvis.memory import MemoryScope

LOCAL = MemoryScope(user_id="local")


class _Repo:
    def __init__(self, histories: dict[str, list] | None = None, fail_on: set[str] | None = None) -> None:
        self._h = histories or {}
        self._fail = fail_on or set()

    async def get_messages(self, session_id: str) -> list:
        if session_id in self._fail:
            raise RuntimeError("repo unavailable")
        return list(self._h.get(session_id, []))


def _make_manager(sessions: dict) -> SessionRegistry:
    mgr = SessionRegistry.__new__(SessionRegistry)
    mgr._ctx = MagicMock()
    mgr._services = MagicMock()
    mgr._sessions = sessions
    mgr._sandboxes = {}
    return mgr


def _mock_session(session_id: str) -> MagicMock:
    s = MagicMock()
    s._session_id = session_id
    s.settle = AsyncMock()
    s.memory_scope = MemoryScope(user_id="local", session_id=session_id)
    return s


def _user_msg(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


@pytest.mark.asyncio
async def test_save_all_stores_episodic(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    model = faux_model_with_response("세션 요약: 사용자가 Python을 배웠습니다.")
    repo = _Repo({"sess1": [_user_msg("Python 배우고 싶어")]})

    await _make_manager({"sess1": _mock_session("sess1")}).save_all_sessions(repo, ltm, model)

    recent = await ltm.recent(LOCAL)
    assert len(recent) == 1
    assert recent[0].session_id == "sess1"
    assert recent[0].source == "session_end"


@pytest.mark.asyncio
async def test_save_all_multiple_sessions(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    model = faux_model_with_response("요약")
    repo = _Repo({"a": [_user_msg("메시지 A")], "b": [_user_msg("메시지 B")]})

    await _make_manager({"a": _mock_session("a"), "b": _mock_session("b")}).save_all_sessions(repo, ltm, model)

    assert {e.session_id for e in await ltm.recent(LOCAL)} == {"a", "b"}


@pytest.mark.asyncio
async def test_save_all_skips_empty_sessions(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    model = faux_model_with_response("요약")
    await _make_manager({"empty": _mock_session("empty")}).save_all_sessions(_Repo(), ltm, model)
    assert await ltm.recent(LOCAL) == []


@pytest.mark.asyncio
async def test_save_all_no_sessions_does_nothing(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    await _make_manager({}).save_all_sessions(_Repo(), ltm, faux_model_with_response("요약"))
    assert await ltm.recent(LOCAL) == []


@pytest.mark.asyncio
async def test_save_all_failure_is_non_fatal():
    ltm = MemoryService(InMemoryItemStore())
    await _make_manager({"crash": _mock_session("crash")}).save_all_sessions(_Repo(fail_on={"crash"}), ltm, MagicMock())
    assert await ltm.recent(LOCAL) == []


@pytest.mark.asyncio
async def test_save_all_partial_failure_continues(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    model = faux_model_with_response("요약")
    repo = _Repo({"ok": [_user_msg("정상 메시지")]}, fail_on={"crash"})
    sessions = {"crash": _mock_session("crash"), "ok": _mock_session("ok")}

    await _make_manager(sessions).save_all_sessions(repo, ltm, model)

    recent = await ltm.recent(LOCAL)
    assert len(recent) == 1 and recent[0].session_id == "ok"


@pytest.mark.asyncio
async def test_summary_lands_in_the_sessions_own_scope(faux_model_with_response):
    """인증된 사용자의 세션 요약은 그 사용자 범위에 private 으로 남아 다른 사용자에게 안 보인다."""
    ltm = MemoryService(InMemoryItemStore())
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

    ltm = MemoryService(InMemoryItemStore(), extractor=extractor)
    model = faux_model_with_response("세션 요약: 부산으로 이사했다")
    session = _mock_session("s")
    session.memory_scope = MemoryScope(user_id="jh", session_id="s")

    await _make_manager({"s": session}).save_all_sessions(_Repo({"s": [_user_msg("부산으로 이사했어")]}), ltm, model)

    facts = await ltm.recent(scope=MemoryScope(user_id="jh", agent_id="researcher"))  # shared 라 서브 에이전트도 본다
    assert [f.content for f in facts] == ["거주지: 부산"]


def test_latest_of_picks_the_session_the_user_talked_to_most_recently():
    """스케줄 결과를 건넬 세션. 사용자가 말한 적 없는 세션(위임받은 세션)은 고르지 않는다."""
    registry = _make_manager({"k1": _mock_session("k1"), "k2": _mock_session("k2"), "peer": _mock_session("peer"),
                              "j": _mock_session("j")})
    registry._session_agents = {"k1": "karen", "k2": "karen", "peer": "karen", "j": "main"}
    registry._last_activity = {}
    assert registry.latest_of("karen") is None
    # touch 는 monotonic 시각이라 연달아 부르면 같을 수 있다. 시각을 직접 둔다
    registry._last_activity.update({"k2": 1.0, "j": 2.0, "k1": 3.0})
    assert registry.latest_of("karen") is registry._sessions["k1"]
    registry._last_activity["k2"] = 4.0
    assert registry.latest_of("karen") is registry._sessions["k2"]
    assert registry.latest_of("main") is registry._sessions["j"]


def _meta(sid: str, agent: str, updated: int, count: int = 4) -> SessionMetadata:
    return SessionMetadata(session_id=sid, cwd=".", created_at=0, updated_at=updated, message_count=count,
                           agent_id=agent)


def test_last_conversation_is_the_latest_saved_talk_not_a_run_or_test():
    """재시작 뒤 건넬 세션: 그 에이전트와 사용자가 나눈 마지막 대화. 스케줄 실행, 위임, 시험, 빈 세션은 뺀다."""
    metas = [
        _meta("a1b2c3d4", "karen", 10), _meta("e5f6a7b8", "karen", 20), _meta("e0e0e0e0", "karen", 90, count=0),
        _meta("sched-goal-x-1", "karen", 99), _meta("peer-main-karen", "karen", 98),
        _meta("live-goal-nl-1", "karen", 97),
        _meta("test-x", "karen", 96), _meta("j1j1j1j1", "main", 95),
    ]
    assert last_conversation(metas, "karen") == "e5f6a7b8"
    assert last_conversation(metas, "main") == "j1j1j1j1"
    assert last_conversation(metas, "ghost") is None


async def test_conversation_of_reopens_the_saved_talk_and_creates_one_only_when_none():
    """열린 대화가 없으면 저장된 마지막 대화를 열고, 그것도 없으면 새로 만든다. 다시 불러도 같은 세션이다."""
    registry = _make_manager({})
    registry._session_agents, registry._last_activity = {}, {}
    registry._ctx.session_repo.list = AsyncMock(return_value=[_meta("a1b2c3d4", "karen", 10)])
    opened: list[str] = []

    async def get_or_create(session_id, agent_id=None, peer=False):  # type: ignore[no-untyped-def]
        opened.append(session_id)
        registry._sessions.setdefault(session_id, _mock_session(session_id))
        registry._session_agents[session_id] = "karen"
        return registry._sessions[session_id], None

    registry.get_or_create = get_or_create  # type: ignore[method-assign]
    registry.create_new = AsyncMock(return_value="newone00")  # type: ignore[method-assign]
    first = await registry.conversation_of("karen")
    again = await registry.conversation_of("karen")
    assert first is again and opened == ["a1b2c3d4"] and registry.create_new.await_count == 0
    registry._ctx.session_repo.list = AsyncMock(return_value=[])
    registry._sessions, registry._session_agents, registry._last_activity = {}, {}, {}
    await registry.conversation_of("karen")
    assert registry.create_new.await_count == 1 and opened[-1] == "newone00"

