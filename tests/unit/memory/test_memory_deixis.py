"""상대 지칭: 회상 질의 보강, 저장 시 가리킨 대화(referent) 기록, 고정 블록 후보와 되뇌기 규칙."""

from datetime import datetime, timedelta

from jarvis.model_layer.types import AssistantMessage, TextContent, ToolResultMessage, UserMessage
from jarvis.memory.working.deixis import has_deixis, recent_exchange, retrieval_query
from jarvis.memory import MemoryKind, MemoryScope, MemoryService, current_scope
from jarvis.core.slash.remember_cmd import make_remember_handler
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.types import REFERENT

CTX = {"session_id": "s1", "user_id": "u1", "agent_id": "main"}
SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")
NOW = datetime(2026, 10, 18, 12, 0)


def _u(text: str) -> UserMessage:
    return UserMessage(content=text, timestamp=0)


def _a(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)], timestamp=0)


def _t(text: str) -> ToolResultMessage:
    return ToolResultMessage(tool_call_id="c", tool_name="bash", content=[TextContent(text=text)])


# ── 순수 함수 ────────────────────────────────────────────────────────────────


def test_has_deixis_catches_korean_and_english_references():
    assert has_deixis("그거 다시 해줘") and has_deixis("아까 말한 방법") and has_deixis("do that again")
    assert has_deixis("그 방식 기억해") and has_deixis("이 계획 괜찮아?")
    assert not has_deixis("서울 날씨 알려줘") and not has_deixis("그래서 결론은")


def test_recent_exchange_skips_tool_results_and_stops_at_user():
    messages = [_u("옛 질문"), _a("옛 답"), _u("배포 스크립트 고쳐줘"), _t("exit 0"), _a("롤백 방식으로 고쳤다")]
    assert recent_exchange(messages) == "배포 스크립트 고쳐줘\n롤백 방식으로 고쳤다"


def test_retrieval_query_prepends_previous_exchange_only_when_needed():
    history = [_u("배포 스크립트 고쳐줘"), _a("롤백 방식으로 고쳤다")]
    assert retrieval_query([*history, _u("그거 스테이징에도 적용해")]).startswith("배포 스크립트 고쳐줘")
    assert retrieval_query([*history, _u("계속")]).startswith("배포 스크립트 고쳐줘")
    assert retrieval_query([*history, _u("서울 날씨 알려줘 주말까지")]) == "서울 날씨 알려줘 주말까지"


# ── 회상 ─────────────────────────────────────────────────────────────────────


async def test_deictic_turn_recalls_memory_about_previous_topic():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
    await memory.remember("배포: 스테이징은 금요일에 막아 둔다", source="session_end", scope=SCOPE)

    out = await memory.observe([_u("배포 일정 정리해줘"), _a("정리했다"), _u("그거 다시 해줘")], CTX)
    assert any("금요일" in m.content for m in out if isinstance(m.content, str))


async def test_fixed_facts_keep_old_important_fact_past_candidate_pool():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=3)
    await memory.remember("이름: 재훈", source="explicit", scope=SCOPE, created_at=NOW - timedelta(days=100))
    for i in range(12):
        await memory.remember(f"취향{i}: 사소함", source="extracted", scope=SCOPE, importance=0.3,
                              created_at=NOW - timedelta(hours=i))
    assert any("재훈" in i.content for i in await memory.fixed_facts(SCOPE))


async def test_fixed_facts_are_not_rehearsed_unless_the_query_hits_them():
    memory = MemoryService(InMemoryItemStore())
    item_id = await memory.remember("선호 음료: 커피", source="explicit", scope=SCOPE)
    for _ in range(3):
        await memory.observe([_u("오늘 일정 알려줘")], CTX)
    assert (await memory.working_state(SCOPE)).rehearsal == {}
    assert (await memory.get(item_id)).last_accessed is None


# ── 저장 시 가리킨 대화 ──────────────────────────────────────────────────────


async def test_referent_is_stored_searched_and_shown():
    memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
    await memory.remember("그 방법 앞으로 계속 써", source="explicit", scope=SCOPE,
                          referent="배포 스크립트 고쳐줘\n롤백 방식으로 고쳤다")

    hits = await memory.recall("롤백", SCOPE)
    assert [h.content for h in hits] == ["그 방법 앞으로 계속 써"]
    out = await memory.observe([_u("롤백 어떻게 하기로 했지")], CTX)
    block = next(m.content for m in out if isinstance(m.content, str) and m.content.startswith("[장기 기억]"))
    assert "(가리킨 대화: 배포 스크립트 고쳐줘 / 롤백 방식으로 고쳤다)" in block


class _Repo:
    def __init__(self, messages):
        self._messages = messages

    async def get_messages(self, session_id: str):
        return self._messages


async def test_remember_command_links_referent_only_for_deictic_content():
    memory = MemoryService(InMemoryItemStore())
    handler = make_remember_handler(memory, _Repo([_u("커밋 메시지 규칙 정해줘"), _a("제목 50자, 본문은 why")]))
    token = current_scope.set(SCOPE)
    try:
        linked = await handler("그거 기억해")
        plain = await handler("거주지: 서울")
    finally:
        current_scope.reset(token)

    assert "가리킨 대화" in linked and "가리킨 대화" not in plain
    items = {i.content: i for i in await memory.recent(SCOPE, kinds=[MemoryKind.SEMANTIC])}
    assert items["그거 기억해"].metadata[REFERENT] == "커밋 메시지 규칙 정해줘\n제목 50자, 본문은 why"
    assert REFERENT not in items["거주지: 서울"].metadata
