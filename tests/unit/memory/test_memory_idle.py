"""idle 공고화: daemon 틱에 얹힌 consolidate 가 사실을 한 번만 뽑고, 실행 중 세션은 건너뛴다."""

from unittest.mock import MagicMock

from jarvis.memory.consolidation.idle import consolidation_targets, should_consolidate_on_idle
from jarvis.memory import MemoryKind, MemoryScope, MemoryService
from jarvis.memory.consolidation.semantic_extract import Fact
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.core.proactive import ProactivityDaemon
from jarvis.config import JarvisSettings

SCOPE = MemoryScope(user_id="jh", agent_id="main", session_id="s1")


def _session(scope: MemoryScope, running: bool = False) -> MagicMock:
    s = MagicMock()
    s.memory_scope = scope
    s.is_running = running
    return s


def test_only_idle_or_both_triggers_consolidate():
    s = JarvisSettings()
    s.proactive.daemon_trigger = "interval"
    assert should_consolidate_on_idle(s) is False
    s.proactive.daemon_trigger = "idle"
    assert should_consolidate_on_idle(s) is True
    s.proactive.daemon_trigger = "both"
    assert should_consolidate_on_idle(s) is True
    s.memory.consolidate_on_idle = False
    assert should_consolidate_on_idle(s) is False


def test_targets_skip_running_sessions_and_bind_scope():
    memory = MemoryService(InMemoryItemStore())
    targets = consolidation_targets(memory, [_session(SCOPE), _session(SCOPE.with_session("s2"), running=True)])
    assert len(targets) == 1
    assert targets[0].args == (SCOPE,)


async def test_daemon_tick_consolidates_once(faux_model_with_response):
    extracted: list[str] = []

    async def extractor(summary: str) -> list[Fact]:
        extracted.append(summary)
        return [Fact("거주지", "부산", 0.9)]

    memory = MemoryService(InMemoryItemStore(), extractor=extractor)
    await memory.remember("세션 요약: 부산으로 이사", source="auto_summary", scope=SCOPE)
    session = _session(SCOPE)

    async def reflect() -> None:
        return None

    daemon = ProactivityDaemon(lambda: [reflect, *consolidation_targets(memory, [session])], interval_sec=0)
    await daemon.tick()
    await daemon.tick()

    assert extracted == ["세션 요약: 부산으로 이사"]  # 두 번째 틱은 다시 뽑지 않는다
    facts = await memory.recent(scope=SCOPE, kinds=[MemoryKind.SEMANTIC])
    assert [f.content for f in facts] == ["거주지: 부산"]


async def test_consolidation_failure_does_not_stop_the_tick():
    memory = MagicMock()

    async def boom(scope):
        raise RuntimeError("db down")

    memory.consolidate = boom
    seen = []

    async def reflect() -> None:
        seen.append("reflect")

    daemon = ProactivityDaemon(lambda: [*consolidation_targets(memory, [_session(SCOPE)]), reflect], interval_sec=0)
    await daemon.tick()
    assert seen == ["reflect"]
