"""/cleanup: 현황은 항상, 삭제는 confirm 이 있을 때만. per_agent 세션은 보존."""

from jarvis.core.slash.cleanup_cmd import make_cleanup_handler
from jarvis.model_layer.types import UserMessage


class _Memory:
    def __init__(self, rows):
        self.rows = rows
        self.dropped = 0

    async def legacy_stm_rows(self):
        return self.rows

    async def drop_legacy_stm(self):
        self.dropped += 1
        self.rows = None


async def _seed(repo):
    for sid in ("agent_researcher", "agent_planner", "agent_researcher__s1", "default", "agent_keep"):
        await repo.create(session_id=sid)
        await repo.append(sid, UserMessage(content="x"))


async def test_status_lists_legacy_sessions_and_stm_rows(jsonl_repo):
    await _seed(jsonl_repo)
    handler = make_cleanup_handler(jsonl_repo, _Memory(42), keep_agent_sessions={"agent_keep"})
    out = await handler("")
    assert "서브 에이전트 세션(옛 형식): 2개" in out and "agent_planner" in out and "agent_keep" not in out
    assert "jarvis_stm_messages: 42행" in out


async def test_agents_requires_confirm_and_preserves_per_agent(jsonl_repo):
    await _seed(jsonl_repo)
    handler = make_cleanup_handler(jsonl_repo, None, keep_agent_sessions={"agent_keep"})
    assert "confirm" in await handler("agents")
    assert {m.session_id for m in await jsonl_repo.list("")} >= {"agent_researcher", "agent_planner"}

    assert "2개를 지웠습니다" in await handler("agents confirm")
    remaining = {m.session_id for m in await jsonl_repo.list("")}
    assert remaining == {"agent_researcher__s1", "default", "agent_keep"}
    assert "없습니다" in await handler("agents confirm")  # 두 번째는 할 일 없음


async def test_stm_requires_confirm_and_drops_once(jsonl_repo):
    memory = _Memory(7)
    handler = make_cleanup_handler(jsonl_repo, memory)
    assert "confirm" in await handler("stm") and memory.dropped == 0
    assert "지웠습니다" in await handler("stm confirm") and memory.dropped == 1
    assert "없거나" in await handler("stm confirm") and memory.dropped == 1


async def test_in_memory_backend_reports_no_table(jsonl_repo):
    handler = make_cleanup_handler(jsonl_repo, _Memory(None))
    assert "없음 또는 Postgres 아님" in await handler("")
    assert "사용법" in await handler("what")
