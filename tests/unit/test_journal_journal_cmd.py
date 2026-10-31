"""journal: /journal 명령이 비어 있음을 알리고 write 로 저널을 남긴 뒤 다시 보여 주는지 검증."""

from jarvis.core.slash.journal_cmd import make_journal_handler
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.agent_layer.journal import ReflectionJournaler
from jarvis.agent_layer.thought.log import THOUGHT_SOURCE
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.scope import MemoryScope

SCOPE = MemoryScope(user_id="local")


async def test_journal_command_shows_empty_then_writes_and_shows(faux_model_with_response):
    ltm = MemoryService(InMemoryItemStore())
    await ltm.remember('{"interpretation":"x"}', source=THOUGHT_SOURCE, scope=SCOPE)
    model = faux_model_with_response(response="메타 관찰 한 줄.")
    handler = make_journal_handler(ReflectionJournaler(model, ltm))

    assert "비어 있습니다" in await handler("", SCOPE)
    assert "메타 관찰" in await handler("write", SCOPE)
    assert "메타 관찰" in await handler("", SCOPE)
