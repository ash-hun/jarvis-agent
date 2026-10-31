"""usermodel: 메모리, JSON 파일 저장소가 저장한 모델을 다시 주고 깨진 스냅샷은 모델 없음으로 읽는지 검증."""

import pytest

from jarvis.agent_layer.usermodel import InMemoryUserModelStore, JsonlUserModelStore, UserModel, UserModelStore


def test_stores_satisfy_protocol(tmp_path):
    assert isinstance(InMemoryUserModelStore(), UserModelStore)
    assert isinstance(JsonlUserModelStore(path=str(tmp_path / "um.json")), UserModelStore)


def in_memory(tmp_path):  # type: ignore[no-untyped-def]
    store = InMemoryUserModelStore()
    return store, lambda: store


def jsonl(tmp_path):  # type: ignore[no-untyped-def]
    path = str(tmp_path / "um.json")
    # 다시 연 저장소에서 읽어 파일에 남았는지 본다
    return JsonlUserModelStore(path=path), lambda: JsonlUserModelStore(path=path)


@pytest.mark.parametrize("make", [in_memory, jsonl])
async def test_store_get_is_none_before_save_and_the_model_after(make, tmp_path):
    store, reopen = make(tmp_path)
    assert await reopen().get() is None

    await store.save(UserModel(summary="유저 요약", traits=["A", "B"], source_count=5))

    got = await reopen().get()
    assert got is not None and got.summary == "유저 요약" and got.traits == ["A", "B"]


async def test_jsonl_usermodel_corrupt_file_is_none(tmp_path):
    path = tmp_path / "um.json"
    path.write_text("{broken", encoding="utf-8")

    assert await JsonlUserModelStore(path=str(path)).get() is None
