"""외부 트리거(Proactive Phase 3) 순수 로직 — 이벤트 추론 / dedup / inbox / 소스 / 폴러."""

from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.config import MCPServerConfig
from jarvis.core.external import (
    ExternalEvent,
    ExternalEventInbox,
    ExternalEventPoller,
    ExternalSource,
    ExternalSourceSpec,
    InMemorySeenStore,
    JsonlSeenStore,
    McpToolSource,
    SeenStore,
    build_mcp_sources,
    derive_events,
    load_source_specs,
)


class _Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class FakeSource:
    """주입한 결과/예외를 그대로 돌려주는 테스트용 소스."""

    def __init__(self, name: str, interval_sec: float, batches: list) -> None:
        self.name = name
        self.interval_sec = interval_sec
        self._batches = list(batches)
        self.calls = 0

    async def poll(self) -> list[ExternalEvent]:
        self.calls += 1
        if not self._batches:
            return []
        item = self._batches.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _event(source: str, key: str, **kw) -> ExternalEvent:
    return ExternalEvent(source=source, key=key, **kw)


# ── derive_events — 키 추론 4경로 ─────────────────────────────────────────────


def test_derive_from_json_array_uses_id_field():
    raw = json.dumps([{"id": "e1", "summary": "회의"}, {"id": "e2", "summary": "리뷰"}])
    events = derive_events("cal", raw)
    assert [e.key for e in events] == ["cal:e1", "cal:e2"]
    assert events[0].title == "회의"


def test_derive_from_wrapped_object_picks_first_list_field():
    raw = json.dumps({"nextPageToken": "x", "messages": [{"messageId": "m1", "subject": "안녕"}]})
    events = derive_events("mail", raw)
    assert len(events) == 1
    assert events[0].key == "mail:m1"
    assert events[0].title == "안녕"


def test_derive_from_object_without_list_field_is_single_item():
    raw = json.dumps({"uid": "only", "name": "단건"})
    events = derive_events("src", raw)
    assert len(events) == 1
    assert events[0].key == "src:only"


def test_derive_from_non_json_is_single_hashed_item():
    events = derive_events("src", "그냥 텍스트 응답")
    assert len(events) == 1
    assert events[0].key.startswith("src:")
    assert events[0].detail == "그냥 텍스트 응답"


def test_derive_hash_key_is_stable_and_content_sensitive():
    a = derive_events("src", json.dumps([{"summary": "회의"}]))[0]
    b = derive_events("src", json.dumps([{"summary": "회의"}]))[0]
    c = derive_events("src", json.dumps([{"summary": "다른 회의"}]))[0]
    assert a.key == b.key
    assert a.key != c.key


def test_derive_truncates_detail_and_skips_empty():
    raw = json.dumps([{"id": "x", "body": "가" * 900}, ""])
    events = derive_events("src", raw, detail_max_chars=50)
    assert len(events) == 1
    assert len(events[0].detail) == 50


def test_derive_extracts_nested_datetime():
    raw = json.dumps([{"id": "e1", "start": {"dateTime": "2026-09-02T10:00:00"}}])
    assert derive_events("cal", raw)[0].occurred_at == "2026-09-02T10:00:00"


def test_derive_empty_raw_yields_nothing():
    assert derive_events("src", "   ") == []


def test_as_line_hides_detail_when_not_requested():
    event = _event("mail", "mail:1", title="제목", detail="본문 비밀", occurred_at="10:00")
    assert "본문 비밀" in event.as_line()
    assert "본문 비밀" not in event.as_line(include_detail=False)
    assert "제목" in event.as_line(include_detail=False)


def test_as_line_falls_back_to_detail_without_title():
    event = _event("src", "src:1", detail="비정형 원문")
    assert "비정형 원문" in event.as_line(include_detail=False)


# ── SeenStore ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_memory_seen_blocks_repoll():
    store = InMemorySeenStore()
    assert isinstance(store, SeenStore)
    events = [_event("s", "s:1"), _event("s", "s:2")]
    assert len(await store.filter_new(events)) == 2
    assert await store.filter_new(events) == []


@pytest.mark.asyncio
async def test_in_memory_seen_expires_by_ttl():
    clock = _Clock()
    store = InMemorySeenStore(ttl_sec=100.0, clock=clock)
    await store.filter_new([_event("s", "s:1")])
    clock.t += 101
    assert len(await store.filter_new([_event("s", "s:1")])) == 1


@pytest.mark.asyncio
async def test_in_memory_seen_truncates_to_max_keys():
    clock = _Clock()
    store = InMemorySeenStore(max_keys=3, clock=clock)
    for i in range(5):
        clock.t += 1
        await store.filter_new([_event("s", f"s:{i}")])
    assert len(store) == 3


@pytest.mark.asyncio
async def test_jsonl_seen_round_trips_across_instances(tmp_path):
    path = str(tmp_path / "seen.jsonl")
    first = JsonlSeenStore(path=path)
    assert len(await first.filter_new([_event("s", "s:1"), _event("s", "s:2")])) == 2

    second = JsonlSeenStore(path=path)
    assert await second.filter_new([_event("s", "s:1")]) == []
    assert len(await second.filter_new([_event("s", "s:3")])) == 1


@pytest.mark.asyncio
async def test_jsonl_seen_prunes_expired_keys_on_load(tmp_path):
    path = str(tmp_path / "seen.jsonl")
    clock = _Clock()
    await JsonlSeenStore(path=path, clock=clock).filter_new([_event("s", "s:1")])

    clock.t += 10_000
    reloaded = JsonlSeenStore(path=path, ttl_sec=100.0, clock=clock)
    assert len(await reloaded.filter_new([_event("s", "s:1")])) == 1


@pytest.mark.asyncio
async def test_jsonl_seen_ignores_corrupt_lines(tmp_path):
    path = tmp_path / "seen.jsonl"
    clock = _Clock()
    path.write_text(
        f'{{"key": "s:1", "ts": {clock.t}}}\nnot json\n{{"no_key": 1}}\n',
        encoding="utf-8",
    )
    store = JsonlSeenStore(path=str(path), clock=clock)
    assert await store.filter_new([_event("s", "s:1")]) == []
    assert len(store) == 1


# ── Inbox ────────────────────────────────────────────────────────────────────


def test_inbox_drain_once():
    inbox = ExternalEventInbox()
    inbox.put([_event("s", "s:1"), _event("s", "s:2")])
    assert len(inbox.drain()) == 2
    assert inbox.drain() == []


def test_inbox_drain_with_limit_keeps_remainder():
    inbox = ExternalEventInbox()
    inbox.put([_event("s", f"s:{i}") for i in range(5)])
    assert len(inbox.drain(limit=2)) == 2
    assert len(inbox) == 3


def test_inbox_counts_dropped_events_on_overflow():
    inbox = ExternalEventInbox(maxlen=2)
    assert inbox.put([_event("s", f"s:{i}") for i in range(5)]) == 3
    assert inbox.dropped == 3
    assert len(inbox.drain()) == 2


# ── McpToolSource ────────────────────────────────────────────────────────────


def _server(**kw) -> MCPServerConfig:
    return MCPServerConfig(name="gcal", transport="stdio", command=["x"], **kw)


def _spec(**kw) -> ExternalSourceSpec:
    base = {"name": "cal", "server": "gcal", "tool": "list_events"}
    return ExternalSourceSpec(**{**base, **kw})


@pytest.mark.asyncio
async def test_mcp_source_passes_args_to_tool_call():
    seen_args: dict = {}

    async def fake_call(server, tool, params):
        seen_args.update({"server": server.name, "tool": tool, "params": params})
        return json.dumps([{"id": "e1", "summary": "회의"}])

    source = McpToolSource(_spec(args={"time_min": "now"}), _server(), call=fake_call)
    events = await source.poll()

    assert seen_args == {"server": "gcal", "tool": "list_events", "params": {"time_min": "now"}}
    assert [e.key for e in events] == ["cal:e1"]
    assert isinstance(source, ExternalSource)


@pytest.mark.asyncio
async def test_mcp_source_returns_empty_on_timeout():
    async def hang(server, tool, params):
        await asyncio.sleep(10)
        return ""

    source = McpToolSource(_spec(), _server(timeout=0.01), call=hang)
    assert await source.poll() == []


@pytest.mark.asyncio
async def test_mcp_source_isolates_errors():
    async def boom(server, tool, params):
        raise RuntimeError("server down")

    assert await McpToolSource(_spec(), _server(), call=boom).poll() == []


def test_build_sources_skips_disabled_and_unknown_server():
    specs = [
        _spec(name="ok"),
        _spec(name="off", enabled=False),
        _spec(name="ghost", server="nope"),
    ]
    sources = build_mcp_sources(specs, [_server()])
    assert [s.name for s in sources] == ["ok"]


# ── YAML 로더 ────────────────────────────────────────────────────────────────


def test_loader_returns_empty_when_dir_missing(tmp_path):
    assert load_source_specs(str(tmp_path / "nope")) == []


def test_loader_parses_list_and_skips_invalid_items(tmp_path):
    (tmp_path / "sources.yaml").write_text(
        "- name: cal\n"
        "  server: gcal\n"
        "  tool: list_events\n"
        "  args: {time_min: now}\n"
        "  interval_sec: 60\n"
        "- name: broken\n"  # server/tool 누락 → skip
        "",
        encoding="utf-8",
    )
    specs = load_source_specs(str(tmp_path))
    assert [s.name for s in specs] == ["cal"]
    assert specs[0].args == {"time_min": "now"}
    assert specs[0].interval_sec == 60


def test_loader_isolates_unparsable_file(tmp_path):
    (tmp_path / "a.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text(
        "name: mail\nserver: gmail\ntool: search\n", encoding="utf-8"
    )
    assert [s.name for s in load_source_specs(str(tmp_path))] == ["mail"]


# ── Poller ───────────────────────────────────────────────────────────────────


def _poller(sources, *, clock, inbox=None, seen=None, trigger=None, **kw):
    return ExternalEventPoller(
        sources,
        # 빈 inbox/seen은 __len__ 때문에 falsy — `or` 대신 None 검사로 넘긴다.
        inbox if inbox is not None else ExternalEventInbox(),
        seen if seen is not None else InMemorySeenStore(),
        trigger=trigger,
        clock=clock,
        **kw,
    )


class _Trigger:
    def __init__(self) -> None:
        self.fired = 0

    def fire(self) -> None:
        self.fired += 1


@pytest.mark.asyncio
async def test_tick_fills_inbox_and_fires_trigger():
    inbox = ExternalEventInbox()
    trigger = _Trigger()
    source = FakeSource("cal", 60.0, [[_event("cal", "cal:1")]])
    poller = _poller([source], clock=_Clock(), inbox=inbox, trigger=trigger)

    assert await poller.tick() == 1
    assert len(inbox) == 1
    assert trigger.fired == 1


@pytest.mark.asyncio
async def test_tick_respects_per_source_interval():
    clock = _Clock()
    fast = FakeSource("fast", 10.0, [[_event("f", f"f:{i}")] for i in range(5)])
    slow = FakeSource("slow", 100.0, [[_event("s", f"s:{i}")] for i in range(5)])
    poller = _poller([fast, slow], clock=clock)

    await poller.tick()  # 최초 틱 — 둘 다 폴링
    clock.t += 10
    await poller.tick()  # fast만 도래
    clock.t += 10
    await poller.tick()

    assert fast.calls == 3
    assert slow.calls == 1


@pytest.mark.asyncio
async def test_tick_deduplicates_repeated_events():
    same = _event("cal", "cal:1")
    source = FakeSource("cal", 1.0, [[same], [same]])
    clock = _Clock()
    poller = _poller([source], clock=clock)

    assert await poller.tick() == 1
    clock.t += 10
    assert await poller.tick() == 0


@pytest.mark.asyncio
async def test_source_exception_does_not_stop_other_sources():
    boom = FakeSource("boom", 1.0, [RuntimeError("down")])
    ok = FakeSource("ok", 1.0, [[_event("ok", "ok:1")]])
    poller = _poller([boom, ok], clock=_Clock())

    assert await poller.tick() == 1


@pytest.mark.asyncio
async def test_tick_caps_events_per_tick():
    batch = [_event("s", f"s:{i}") for i in range(30)]
    poller = _poller([FakeSource("s", 1.0, [batch])], clock=_Clock(), max_events_per_tick=5)
    assert await poller.tick() == 5


@pytest.mark.asyncio
async def test_loop_sleeps_until_next_due_and_stops():
    clock = _Clock()
    slept: list[float] = []
    source = FakeSource("cal", 30.0, [[_event("cal", "cal:1")]])
    poller = ExternalEventPoller(
        [source],
        ExternalEventInbox(),
        InMemorySeenStore(),
        clock=clock,
        sleep=lambda d: _record_and_yield(slept, d),
    )
    await poller.start()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await poller.stop()

    assert source.calls >= 1
    assert slept and slept[0] == 30.0
    assert not poller.is_running


async def _record_and_yield(bucket: list[float], delay: float) -> None:
    bucket.append(delay)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_start_is_noop_without_sources():
    poller = _poller([], clock=_Clock())
    await poller.start()
    assert not poller.is_running
