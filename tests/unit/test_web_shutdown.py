"""Web HUD 세션 종료 훅 — save_all_sessions 단위 테스트."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from jarvis.agent_layer.memory.backends.sqlite_ltm import SqliteLTMBackend
from jarvis.agent_layer.memory.backends.sqlite_stm import SqliteSTMBackend
from jarvis.model_layer.types import UserMessage
from jarvis.ui.web.server import SessionManager


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
    return s


def _user_msg(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


# ── save_all_sessions ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_all_stores_episodic(faux_model_with_response, tmp_path):
    """활성 세션이 있으면 LTM에 에피소딕 요약이 저장된다."""
    stm = SqliteSTMBackend(db_path=str(tmp_path / "stm.db"))
    ltm = SqliteLTMBackend(db_path=str(tmp_path / "ltm.db"))
    model = faux_model_with_response("세션 요약: 사용자가 Python을 배웠습니다.")

    await stm.append("sess1", _user_msg("Python 배우고 싶어"))

    mgr = _make_manager({"sess1": _mock_session("sess1")})
    await mgr.save_all_sessions(stm, ltm, model)

    recent = await ltm.get_recent()
    assert len(recent) == 1
    assert recent[0].session_id == "sess1"
    assert recent[0].source == "session_end"


@pytest.mark.asyncio
async def test_save_all_multiple_sessions(faux_model_with_response, tmp_path):
    """세션이 여럿이면 모두 저장된다."""
    stm = SqliteSTMBackend(db_path=str(tmp_path / "stm.db"))
    ltm = SqliteLTMBackend(db_path=str(tmp_path / "ltm.db"))
    model = faux_model_with_response("요약")

    await stm.append("a", _user_msg("메시지 A"))
    await stm.append("b", _user_msg("메시지 B"))

    mgr = _make_manager({
        "a": _mock_session("a"),
        "b": _mock_session("b"),
    })
    await mgr.save_all_sessions(stm, ltm, model)

    recent = await ltm.get_recent()
    assert len(recent) == 2
    session_ids = {e.session_id for e in recent}
    assert session_ids == {"a", "b"}


@pytest.mark.asyncio
async def test_save_all_skips_empty_sessions(faux_model_with_response, tmp_path):
    """STM에 메시지가 없는 세션은 LTM에 저장하지 않는다."""
    stm = SqliteSTMBackend(db_path=str(tmp_path / "stm.db"))
    ltm = SqliteLTMBackend(db_path=str(tmp_path / "ltm.db"))
    model = faux_model_with_response("요약")

    # "empty" 세션은 STM에 메시지 없음
    mgr = _make_manager({"empty": _mock_session("empty")})
    await mgr.save_all_sessions(stm, ltm, model)

    assert await ltm.get_recent() == []


@pytest.mark.asyncio
async def test_save_all_no_sessions_does_nothing(faux_model_with_response, tmp_path):
    """활성 세션이 없으면 아무것도 저장하지 않는다."""
    stm = SqliteSTMBackend(db_path=str(tmp_path / "stm.db"))
    ltm = SqliteLTMBackend(db_path=str(tmp_path / "ltm.db"))
    model = faux_model_with_response("요약")

    mgr = _make_manager({})
    await mgr.save_all_sessions(stm, ltm, model)

    assert await ltm.get_recent() == []


@pytest.mark.asyncio
async def test_save_all_failure_is_non_fatal(tmp_path):
    """개별 세션 저장 실패는 다른 세션 처리를 막지 않는다."""
    from unittest.mock import AsyncMock

    stm = AsyncMock()
    stm.load.side_effect = RuntimeError("STM unavailable")

    ltm = SqliteLTMBackend(db_path=str(tmp_path / "ltm.db"))
    model = MagicMock()

    mgr = _make_manager({"crash": _mock_session("crash")})
    # 예외가 전파되지 않아야 한다
    await mgr.save_all_sessions(stm, ltm, model)

    assert await ltm.get_recent() == []


@pytest.mark.asyncio
async def test_save_all_partial_failure_continues(faux_model_with_response, tmp_path):
    """한 세션이 실패해도 나머지 세션은 계속 저장된다."""
    from unittest.mock import AsyncMock

    stm = AsyncMock()

    async def load_side_effect(session_id: str):
        if session_id == "crash":
            raise RuntimeError("crash!")
        return [_user_msg("정상 메시지")]

    stm.load.side_effect = load_side_effect

    ltm = SqliteLTMBackend(db_path=str(tmp_path / "ltm.db"))
    model = faux_model_with_response("요약")

    mgr = _make_manager({
        "crash": _mock_session("crash"),
        "ok": _mock_session("ok"),
    })
    await mgr.save_all_sessions(stm, ltm, model)

    recent = await ltm.get_recent()
    assert len(recent) == 1
    assert recent[0].session_id == "ok"
