"""[agent_layer] 사용자 모델(타입, 저장소, 빌더, 명령) 테스트."""

import json
import pytest

from jarvis.agent_layer.usermodel import (
    InMemoryUserModelStore,
    JsonlUserModelStore,
    UserModel,
    UserModelBuilder,
    UserModelStore,
)

# ── 타입 ──────────────────────────────────────────────────────────────────────

def test_empty_model_context_is_blank():
    assert UserModel().is_empty() is True
    assert UserModel().as_context() == ""


def test_context_block_includes_summary_and_traits():
    m = UserModel(summary="간결한 답을 선호", traits=["Python 사용", "테스트 중시"])
    block = m.as_context()
    assert "[사용자 모델]" in block
    assert "간결한 답" in block
    assert "Python 사용" in block and "테스트 중시" in block


# ── 저장소 ────────────────────────────────────────────────────────────────────

def test_stores_satisfy_protocol(tmp_path):
    assert isinstance(InMemoryUserModelStore(), UserModelStore)
    assert isinstance(JsonlUserModelStore(path=str(tmp_path / "um.json")), UserModelStore)


@pytest.mark.asyncio
async def test_in_memory_save_get():
    store = InMemoryUserModelStore()
    assert await store.get() is None
    await store.save(UserModel(summary="x"))
    assert (await store.get()).summary == "x"


@pytest.mark.asyncio
async def test_jsonl_persists_across_reload(tmp_path):
    path = str(tmp_path / "um.json")
    s1 = JsonlUserModelStore(path=path)
    await s1.save(UserModel(summary="유저 요약", traits=["A", "B"], source_count=5))

    s2 = JsonlUserModelStore(path=path)
    got = await s2.get()
    assert got is not None
    assert got.summary == "유저 요약" and got.traits == ["A", "B"]


@pytest.mark.asyncio
async def test_jsonl_missing_file_is_none(tmp_path):
    s = JsonlUserModelStore(path=str(tmp_path / "nope.json"))
    assert await s.get() is None


# ── 빌더 ──────────────────────────────────────────────────────────────────────

def _model_json(summary="간결·직접적 답 선호", traits=None):
    return json.dumps(
        {"summary": summary, "traits": traits or ["Python", "테스트 우선"]},
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_builder_distills_model(faux_model_with_response):
    model = faux_model_with_response(response=_model_json())
    builder = UserModelBuilder(model=model)

    result = await builder.build(["세션 요약 1", "세션 요약 2"])
    assert result is not None
    assert result.summary == "간결·직접적 답 선호"
    assert "Python" in result.traits
    assert result.source_count == 2


@pytest.mark.asyncio
async def test_builder_empty_sources_keeps_previous(faux_model_with_response):
    model = faux_model_with_response(response=_model_json())
    builder = UserModelBuilder(model=model)
    prev = UserModel(summary="이전")
    assert await builder.build([], previous=prev) is prev


@pytest.mark.asyncio
async def test_builder_broken_json_keeps_previous(faux_model_with_response):
    model = faux_model_with_response(response="JSON 아님")
    builder = UserModelBuilder(model=model)
    prev = UserModel(summary="이전")
    assert await builder.build(["소스"], previous=prev) is prev


# ── 명령 ──────────────────────────────────────────────────────────────────────

class _FakeLTM:
    def __init__(self, contents):
        self._contents = contents

    async def recent(self, limit=10):
        from jarvis.memory import MemoryItem, MemoryKind, MemoryScope

        scope = MemoryScope(user_id="local")
        return [
            MemoryItem(content=c, kind=MemoryKind.SEMANTIC, scope=scope, source="x") for c in self._contents[:limit]
        ]


@pytest.mark.asyncio
async def test_usermodel_command_build_and_show(faux_model_with_response):
    from jarvis.core.slash.usermodel_cmd import make_usermodel_handler

    model = faux_model_with_response(response=_model_json())
    store = InMemoryUserModelStore()
    handler = make_usermodel_handler(
        store, UserModelBuilder(model=model), _FakeLTM(["요약 A", "요약 B"])
    )

    # show: 아직 없음
    assert "아직 모델이 없습니다" in await handler("")

    # build → 저장 + 표시
    out = await handler("build")
    assert "간결·직접적" in out
    assert (await store.get()).summary == "간결·직접적 답 선호"

    # show: 이제 표시됨
    assert "간결·직접적" in await handler("")
