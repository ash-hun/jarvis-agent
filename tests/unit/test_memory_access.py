"""memory 기능의 접근 정책: 층별 읽기 소유자 계산, 저장소에서의 강제, 에이전트 정의의 memory 블록."""

import pytest

from jarvis.memory.access import MemoryPolicy, MemoryReadPolicy, Readable, readable_owners, resolve
from jarvis.app.agent_registry import AgentSpec, load_agent_specs
from jarvis.memory import MemoryKind, MemoryScope, MemoryService
from jarvis.memory.stores.in_memory import InMemoryItemStore

MAIN = MemoryScope(user_id="u1", agent_id="main")
KAREN = MemoryScope(user_id="u1", agent_id="karen")
POLICIES = {"karen": MemoryPolicy(read=MemoryReadPolicy(edm=["self", "main"], pdm=["main"]))}


@pytest.mark.parametrize(
    ("policies", "agent", "expected"),
    [
        ({}, "main", Readable.own("main")),
        (POLICIES, "karen", Readable(edm=frozenset({"karen", "main"}), pdm=frozenset({"karen", "main"}))),
    ],
    ids=["unlisted_reads_own_only", "self_readable_even_if_omitted"],
)
def test_resolve_grants_listed_layers_plus_self(policies, agent, expected):
    readable = resolve(policies, agent)

    assert (readable.edm, readable.pdm) == (expected.edm, expected.pdm)


def test_user_profile_is_not_restricted_by_owner():
    assert readable_owners(Readable.own("main"), MemoryKind.SEMANTIC) is None
    assert readable_owners(Readable.own("main"), MemoryKind.EPISODIC) == {"main"}


@pytest.fixture
def memory() -> MemoryService:
    return MemoryService(InMemoryItemStore(), policies=POLICIES)


async def test_grant_is_one_way_and_per_layer(memory):
    await memory.remember("공고 작업: 분양가 표", source="session_end", scope=MAIN)
    await memory.remember("공고 작업 절차", source="eval", scope=MAIN, kind=MemoryKind.PROCEDURAL)
    await memory.remember("공고 작업: 대출 계산", source="session_end", scope=KAREN)

    # karen 은 main 의 EDM 과 PDM 을 허락받았다
    assert {i.content for i in await memory.recall("공고 작업", KAREN)} == {
        "공고 작업: 분양가 표", "공고 작업 절차", "공고 작업: 대출 계산"
    }
    # main 은 허락받지 않았다. shared 로 써도 다른 에이전트의 일화는 보이지 않는다
    await memory.remember("공고 작업: 공유 결과", source="promoted", scope=KAREN)
    assert {i.content for i in await memory.recall("공고 작업", MAIN)} == {"공고 작업: 분양가 표", "공고 작업 절차"}


async def test_other_user_is_denied_before_policy(memory):
    await memory.remember("공고 작업: 남의 것", source="session_end", scope=MemoryScope(user_id="u2", agent_id="main"))

    assert await memory.recall("공고 작업", KAREN) == []


def test_agent_spec_parses_memory_block_and_rejects_unknown_keys():
    spec = AgentSpec.model_validate({"name": "K", "memory": {"read": {"pdm": ["self", "main"]}}})

    assert spec.memory.read.pdm == ["self", "main"] and spec.memory.read.edm == ["self"]
    with pytest.raises(ValueError):
        AgentSpec.model_validate({"name": "K", "memory": {"read": {"stm": ["main"]}}})


def test_shipped_team_specs_keep_default_policy():
    """레포의 team/ 정의는 정책을 바꾸지 않는다. 열려면 사람이 파일에 적는다."""
    for spec in load_agent_specs("team").values():
        assert spec.memory == MemoryPolicy()
