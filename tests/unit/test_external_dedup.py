"""external 기능의 dedup: 원문을 이벤트로 쪼개는 키 추론과 이미 본 이벤트 거르기를 검증한다."""

import json
import pytest

from jarvis.core.external import InMemorySeenStore, JsonlSeenStore, SeenStore, derive_events, ExternalEvent
from tests.fixtures.external_helpers import Clock, event


@pytest.mark.parametrize(
    ("source", "raw", "keys", "first_title"),
    [
        (
            "cal",
            json.dumps([{"id": "e1", "summary": "회의"}, {"id": "e2", "summary": "리뷰"}]),
            ["cal:e1", "cal:e2"],
            "회의",
        ),
        (
            "mail",
            json.dumps({"nextPageToken": "x", "messages": [{"messageId": "m1", "subject": "안녕"}]}),
            ["mail:m1"],
            "안녕",
        ),
        ("src", json.dumps({"uid": "only", "name": "단건"}), ["src:only"], "단건"),
    ],
    ids=["json_array", "wrapped_object_first_list_field", "object_without_list_is_single_item"],
)
def test_derive_events_infers_key_from_id_field(source: str, raw: str, keys: list[str], first_title: str) -> None:
    events = derive_events(source, raw)

    assert [e.key for e in events] == keys
    assert events[0].title == first_title


def test_derive_events_non_json_becomes_single_hashed_item() -> None:
    events = derive_events("src", "그냥 텍스트 응답")

    assert len(events) == 1
    assert events[0].key.startswith("src:")
    assert events[0].detail == "그냥 텍스트 응답"


def test_derive_events_hash_key_is_stable_and_content_sensitive() -> None:
    a = derive_events("src", json.dumps([{"summary": "회의"}]))[0]
    b = derive_events("src", json.dumps([{"summary": "회의"}]))[0]

    c = derive_events("src", json.dumps([{"summary": "다른 회의"}]))[0]

    assert a.key == b.key
    assert a.key != c.key


def test_derive_events_truncates_detail_and_skips_empty_items() -> None:
    raw = json.dumps([{"id": "x", "body": "가" * 900}, ""])

    events = derive_events("src", raw, detail_max_chars=50)

    assert len(events) == 1
    assert len(events[0].detail) == 50


def test_derive_events_extracts_nested_datetime() -> None:
    raw = json.dumps([{"id": "e1", "start": {"dateTime": "2026-09-02T10:00:00"}}])

    assert derive_events("cal", raw)[0].occurred_at == "2026-09-02T10:00:00"


def test_derive_events_blank_raw_yields_nothing() -> None:
    assert derive_events("src", "   ") == []


@pytest.mark.asyncio
async def test_in_memory_seen_blocks_repoll() -> None:
    store = InMemorySeenStore()
    events = [event("s", "s:1"), event("s", "s:2")]

    first = await store.filter_new(events)

    assert isinstance(store, SeenStore)
    assert len(first) == 2
    assert await store.filter_new(events) == []


@pytest.mark.asyncio
async def test_in_memory_seen_expires_after_ttl() -> None:
    clock = Clock()
    store = InMemorySeenStore(ttl_sec=100.0, clock=clock)
    await store.filter_new([event("s", "s:1")])

    clock.t += 101

    assert len(await store.filter_new([event("s", "s:1")])) == 1


@pytest.mark.asyncio
async def test_in_memory_seen_truncates_to_max_keys() -> None:
    clock = Clock()
    store = InMemorySeenStore(max_keys=3, clock=clock)

    for i in range(5):
        clock.t += 1
        await store.filter_new([event("s", f"s:{i}")])

    assert len(store) == 3


@pytest.mark.asyncio
async def test_jsonl_seen_survives_new_instance(tmp_path) -> None:
    path = str(tmp_path / "seen.jsonl")
    assert len(await JsonlSeenStore(path=path).filter_new([event("s", "s:1"), event("s", "s:2")])) == 2

    second = JsonlSeenStore(path=path)

    assert await second.filter_new([event("s", "s:1")]) == []
    assert len(await second.filter_new([event("s", "s:3")])) == 1


@pytest.mark.asyncio
async def test_jsonl_seen_prunes_expired_keys_on_load(tmp_path) -> None:
    path = str(tmp_path / "seen.jsonl")
    clock = Clock()
    await JsonlSeenStore(path=path, clock=clock).filter_new([event("s", "s:1")])
    clock.t += 10_000

    reloaded = JsonlSeenStore(path=path, ttl_sec=100.0, clock=clock)

    assert len(await reloaded.filter_new([event("s", "s:1")])) == 1


@pytest.mark.asyncio
async def test_jsonl_seen_ignores_corrupt_lines(tmp_path) -> None:
    path = tmp_path / "seen.jsonl"
    clock = Clock()
    path.write_text(f'{{"key": "s:1", "ts": {clock.t}}}\nnot json\n{{"no_key": 1}}\n', encoding="utf-8")

    store = JsonlSeenStore(path=str(path), clock=clock)

    assert await store.filter_new([event("s", "s:1")]) == []
    assert len(store) == 1


async def test_seen_store_default_passes_everything_twice():
    store = SeenStore()
    events = [ExternalEvent(source="s", key="s:1")]

    assert await store.filter_new(events) == events
    assert await store.filter_new(events) == events  # 기억하지 않는다


def test_seen_store_implementations_inherit(tmp_path):
    assert isinstance(InMemorySeenStore(), SeenStore)
    assert isinstance(JsonlSeenStore(path=str(tmp_path / "seen.jsonl")), SeenStore)
