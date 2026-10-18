"""기반 클래스: Protocol 대신 쓰는 ItemStore, WorkingStore, ProceduralSource, EvalTarget 의 기본 동작과 상속 관계."""

from datetime import datetime
from types import SimpleNamespace

from jarvis.memory.long_term.procedural import (
    InMemoryProcedures,
    ProceduralSource,
    Procedure,
    SkillRegistryProcedures,
)
from jarvis.memory import MemoryItem, MemoryKind, MemoryScope, MemoryService
from jarvis.memory.eval.target import TARGETS, EvalTarget, StoreTarget
from jarvis.memory.working.state import WorkingState, WorkingStore
from jarvis.memory.working.in_memory import InMemoryWorkingStore
from jarvis.memory.working.postgres import PostgresWorkingStore
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.stores.postgres import PostgresItemStore
from jarvis.memory.eval.fake_embedder import FakeEmbedder
from jarvis.memory.stores.protocol import ItemStore
from jarvis.model_layer.embeddings import Embedder
from jarvis.memory.eval.schema import SetupStep

SCOPE = MemoryScope(user_id="u1", agent_id="main", session_id="s1")


def _item(content: str) -> MemoryItem:
    return MemoryItem(content=content, kind=MemoryKind.SEMANTIC, scope=SCOPE)


def test_concrete_stores_inherit_their_bases():
    assert isinstance(InMemoryItemStore(), ItemStore)
    assert isinstance(PostgresItemStore(dsn="postgresql://unused"), ItemStore)  # 생성만 하고 접속하지 않는다
    assert isinstance(InMemoryWorkingStore(), WorkingStore)
    assert isinstance(PostgresWorkingStore(dsn="postgresql://unused"), WorkingStore)
    assert isinstance(InMemoryProcedures(), ProceduralSource)
    assert isinstance(SkillRegistryProcedures(object()), ProceduralSource)
    assert isinstance(StoreTarget(), EvalTarget)
    assert isinstance(FakeEmbedder(), Embedder)


async def test_item_store_base_is_a_working_in_memory_store():
    store = ItemStore()
    old, new = _item("거주지: 부산"), _item("거주지: 서울")
    assert await store.store(old) == old.id
    await store.store(new)
    assert await store.get(old.id) is old
    assert {i.id for i in await store.search("거주지", SCOPE)} == {old.id, new.id}
    await store.supersede(old.id, new.id)
    assert [i.id for i in await store.recent(SCOPE)] == [new.id]
    at = datetime(2024, 1, 1)
    await store.touch([new.id, "missing"], at)
    assert new.last_accessed == at
    await store.delete(new.id)
    assert await store.get(new.id) is None
    await store.clear()
    assert await store.get(old.id) is None


async def test_item_store_search_without_tokens_or_vector_is_empty():
    store = ItemStore()
    await store.store(_item("anything"))
    assert await store.search("   ", SCOPE) == []


async def test_working_store_base_roundtrip_and_legacy_defaults():
    store = WorkingStore()
    state = WorkingState(scope=SCOPE, summary="요약", summary_covers=3)
    await store.save(state)
    loaded = await store.load(SCOPE)
    assert (loaded.summary, loaded.summary_covers) == ("요약", 3)
    await store.clear(SCOPE)
    assert (await store.load(SCOPE)).summary is None
    assert await store.legacy_stm_rows() is None
    await store.drop_legacy_stm()  # 지울 것이 없어도 에러 없이


async def test_memory_service_legacy_stm_on_in_memory_store_is_none():
    memory = MemoryService(InMemoryItemStore())
    assert await memory.legacy_stm_rows() is None
    await memory.drop_legacy_stm()


def test_procedural_source_base_knows_nothing():
    assert ProceduralSource().match("deploy") == []


def test_in_memory_procedures_match_by_name_or_alias():
    source = InMemoryProcedures([Procedure(name="deploy", description="배포", aliases=("배포",))])
    source.add(Procedure(name="review", description="리뷰"))
    assert [p.name for p in source.match("스테이징 배포 해줘")] == ["deploy"]
    assert [p.name for p in source.match("review this")] == ["review"]
    assert source.match("deployment") == []  # 부분 일치는 매칭하지 않는다


def test_skill_registry_procedures_read_registry_live():
    skills = [SimpleNamespace(name="deploy", description=None, aliases=["배포"])]
    registry = SimpleNamespace(list_all=lambda: skills)
    source = SkillRegistryProcedures(registry)
    matched = source.match("배포")
    assert [(p.name, p.description, p.aliases) for p in matched] == [("deploy", "", ("배포",))]
    skills.append(SimpleNamespace(name="lint", description="정적 검사"))
    assert [p.name for p in source.match("lint")] == ["lint"]
    assert SkillRegistryProcedures(object()).match("deploy") == []  # list_all 이 없는 레지스트리


async def test_eval_target_base_remembers_probes_and_resets():
    target = EvalTarget()
    await target.setup(SetupStep(remember="거주지: 서울"), SCOPE)
    await target.setup(SetupStep(skill="deploy", description="배포", aliases=["배포"]), SCOPE)
    assert await target.probe("거주지", SCOPE, top_k=3) == ["거주지: 서울"]
    assert await target.probe("배포", SCOPE, top_k=3, kind="procedures") == ["deploy"]
    await target.reset()
    assert await target.probe("거주지", SCOPE, top_k=3) == []
    assert TARGETS["store"] is StoreTarget
