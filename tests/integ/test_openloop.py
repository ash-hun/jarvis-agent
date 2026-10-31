"""openloop 기능: AGENDA 흐름, Postgres 에이전트 칼럼, 세션이 약속을 저장하고 닫고 사고와 판단에 보여주는지 검증한다."""

import time
import pytest
import asyncio
from datetime import datetime

pytest.importorskip("fastapi")

from tests.fixtures.openloop_helpers import (  # noqa: E402
    SESSION_ID,
    CapturingEngine,
    CapturingJudge,
    build_session,
    say,
)
from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, LoopExpiry, OpenLoop  # noqa: E402
from tests.fixtures.web_hud_helpers import agenda_assembly, web_client  # noqa: E402
from jarvis.agent_layer.agent_types import AgendaChangedEvent  # noqa: E402
from jarvis.agent_layer.openloop.judge import LoopVerdict  # noqa: E402
from jarvis.core.proactive import DefaultProactivityCore  # noqa: E402
from jarvis.model_layer.model_types import UserMessage  # noqa: E402


HOUR_MS = 3600 * 1000


@pytest.fixture
def agenda(monkeypatch, tmp_path):
    assembly, _ = agenda_assembly(monkeypatch, tmp_path)
    with web_client(assembly) as c:
        yield c, assembly.services.openloop_store


def test_agenda_lists_open_loops_and_schedules_after_expiring_overdue(agenda):
    client, store = agenda
    now_ms = int(time.time() * 1000)
    loop_id = asyncio.run(store.add(OpenLoop(description="리뷰 자료 보내기", origin_session="default")))
    soon = asyncio.run(store.add(OpenLoop(description="곧 할 일", due_ms=now_ms + HOUR_MS)))
    # 기본 여유(6시간)보다 오래 지난 기한은 화면에 오기 전에 expired 로 닫힌다
    old = asyncio.run(store.add(OpenLoop(description="어제 회의 준비", due_ms=now_ms - 7 * HOUR_MS)))

    body = client.get("/api/agenda").json()

    assert {lp["id"]: lp["description"] for lp in body["open_loops"]} == {
        loop_id: "리뷰 자료 보내기", soon: "곧 할 일"
    }
    assert asyncio.run(store.get(old)).status == "expired"
    names = [s["name"] for s in body["schedules"]]
    off = next(s for s in body["schedules"] if s["name"] == "off")
    assert set(names) == {"late", "off"}
    # 꺼진 작업은 다음 실행이 없고 목록 아래로 간다
    assert off["enabled"] is False and off["next_run"] is None
    assert names[-1] == "off"


def test_done_loop_leaves_agenda_and_reopens_but_an_overdue_one_does_not(agenda):
    client, store = agenda
    now_ms = int(time.time() * 1000)
    keep = asyncio.run(store.add(OpenLoop(description="리뷰 자료 보내기", origin_session="default")))
    late = asyncio.run(store.add(OpenLoop(description="어제 회의 준비", due_ms=now_ms - 7 * HOUR_MS)))
    asyncio.run(store.update_status(late, "done"))

    done = client.post(f"/api/openloops/{keep}", json={"status": "done"})
    closed = client.get("/api/agenda").json()
    reopened = [client.post(f"/api/openloops/{keep}", json={"status": "open"}) for _ in range(2)]
    after = client.get("/api/agenda").json()
    # 기한이 한참 지난 약속은 열어도 바로 만료되므로 거절한다
    refused = client.post(f"/api/openloops/{late}", json={"status": "open"})

    assert done.status_code == 200
    assert closed["open_loops"] == []
    assert {lp["id"]: lp["status"] for lp in closed["closed_loops"]} == {keep: "done", late: "done"}
    assert all(r.status_code == 200 and r.json() == {"id": keep, "status": "open"} for r in reopened)
    assert [lp["id"] for lp in after["open_loops"]] == [keep]
    assert [lp["id"] for lp in after["closed_loops"]] == [late]
    assert refused.status_code == 409
    assert asyncio.run(store.get(late)).status == "done"


@pytest.mark.parametrize(("status", "code"), [("maybe", 400), ("open", 404), ("done", 404)])
def test_openloop_rejects_bad_status_and_unknown_id(agenda, status, code):
    client, _ = agenda

    resp = client.post("/api/openloops/nope", json={"status": status})

    assert resp.status_code == code


@pytest.fixture(scope="module")
def postgres_dsn():
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    pytest.importorskip("asyncpg", reason="asyncpg not installed")
    from testcontainers.postgres import PostgresContainer

    try:
        with PostgresContainer("pgvector/pgvector:pg16") as pg:
            yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")
    except Exception as exc:
        pytest.skip(f"Docker unavailable or container failed to start: {exc}")


async def test_pg_agent_column_added_to_old_table_and_round_trips(postgres_dsn):
    import asyncpg

    from jarvis.agent_layer.openloop import PostgresOpenLoopStore

    conn = await asyncpg.connect(postgres_dsn)
    try:
        await conn.execute("DROP TABLE IF EXISTS jarvis_open_loops")
        await conn.execute("""
            CREATE TABLE jarvis_open_loops (
                id TEXT PRIMARY KEY, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
                origin_session TEXT, due_ms BIGINT, created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
            )
        """)
        await conn.execute(
            "INSERT INTO jarvis_open_loops (id, description, created_at, updated_at) VALUES ('old', '옛 약속', 1, 1)"
        )
    finally:
        await conn.close()

    for _ in range(2):  # 두 번 열어도 같은 상태
        store = PostgresOpenLoopStore(dsn=postgres_dsn)
        await store.add(OpenLoop(id="new", description="뉴스 정리", agent_id="karen"))
        loops = {lp.id: lp.agent_id for lp in await store.list_open()}
        await store.close()

        assert loops == {"old": "main", "new": "karen"}


@pytest.fixture
async def fx(faux_model, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo):
    await jsonl_repo.create(session_id=SESSION_ID)
    return {
        "model": faux_model,
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }


async def _open_loop(store, description: str, **kwargs) -> str:
    return await store.add(OpenLoop(description=description, origin_session=SESSION_ID, **kwargs))


async def test_detected_open_loops_are_persisted(fx):
    store = InMemoryOpenLoopStore()
    judge = CapturingJudge(LoopVerdict(open_loops=["내일 배포 결과 공유", "리뷰 답변"]))
    session = build_session(fx, CapturingEngine(), store, judge=judge)

    await say(session, "내일 배포 결과 공유하고 리뷰 답변도 할게")

    loops = await store.list_open(session_id=SESSION_ID)
    assert {x.description for x in loops} == {"내일 배포 결과 공유", "리뷰 답변"}
    assert all(x.origin_session == SESSION_ID for x in loops)


async def test_open_loops_carry_session_agent(fx):
    store = InMemoryOpenLoopStore()
    session = build_session(fx, CapturingEngine(), store, judge=CapturingJudge(LoopVerdict(open_loops=["뉴스 정리"])))
    session.agent_name = "karen"

    await say(session, "뉴스 정리해 줄게")

    assert [x.agent_id for x in await store.list_open(session_id=SESSION_ID)] == ["karen"]


async def test_open_loops_deduped_across_turns(fx):
    store = InMemoryOpenLoopStore()
    session = build_session(fx, CapturingEngine(), store, judge=CapturingJudge(LoopVerdict(open_loops=["같은 약속"])))

    await say(session, "같은 약속 첫 턴")
    await say(session, "같은 약속 둘째 턴")

    assert len(await store.list_open()) == 1


async def test_open_loops_are_tracked_without_thought(fx):
    store = InMemoryOpenLoopStore()
    session = build_session(fx, None, store, judge=CapturingJudge(LoopVerdict(open_loops=["보고서 보내기"])))

    await say(session, "내일까지 보고서 보내기로 했어")

    assert [x.description for x in await store.list_open()] == ["보고서 보내기"]


async def test_open_loops_not_in_input_are_dropped(fx):
    store = InMemoryOpenLoopStore()
    # 회상된 기억 속 약속을 새로 흘린 것처럼 옮겨 적은 경우
    judge = CapturingJudge(LoopVerdict(open_loops=["핵심 메시지 3가지 구조화 작업", "분기 보고서 초안 제출"]))
    session = build_session(fx, CapturingEngine(), store, judge=judge)

    await say(session, "내일까지 분기 보고서 초안 보내야 해")

    assert [x.description for x in await store.list_open()] == ["분기 보고서 초안 제출"]


async def test_existing_open_loops_recalled_into_request(fx):
    store = InMemoryOpenLoopStore()
    await _open_loop(store, "기존 약속 A")
    engine = CapturingEngine()
    session = build_session(fx, engine, store)

    await say(session, "새 입력")

    assert engine.requests[0].open_loops == ["[1] 기존 약속 A"]


async def test_judge_sees_numbered_open_loops(fx):
    store = InMemoryOpenLoopStore()
    await _open_loop(store, "리뷰 답변")
    judge = CapturingJudge()
    session = build_session(fx, CapturingEngine(), store, judge=judge)

    await say(session, "리뷰 답변 끝냈어")

    assert judge.calls == [("리뷰 답변 끝냈어", ["[1] 리뷰 답변"])]


async def test_no_store_is_noop(fx):
    engine = CapturingEngine()
    session = build_session(fx, engine, None, judge=CapturingJudge(LoopVerdict(open_loops=["무시됨"])))

    result = await session.prompt("입력")

    assert result is not None
    assert engine.requests[0].open_loops == []


@pytest.mark.parametrize(
    "verdict",
    [LoopVerdict(open_loops=["참석자들의 최종 리스트 확정"]), LoopVerdict(closed_loops=["참석자 목록 확정"])],
)
async def test_reflection_neither_adds_nor_closes_loops(fx, verdict):
    await fx["repo"].append(SESSION_ID, UserMessage(content="참석자 목록 확정해야 해"))
    store = InMemoryOpenLoopStore()
    await _open_loop(store, "참석자 목록 확정")
    engine = CapturingEngine()
    judge = CapturingJudge(verdict)
    session = build_session(
        fx, engine, store, judge=judge, proactivity_factory=lambda emit: DefaultProactivityCore(emit_proactive=emit)
    )

    await session.reflect()

    assert engine.requests[0].mode == "reflection"
    assert judge.calls == []  # AGENDA 판단은 사용자 입력이 있는 턴에만 돈다
    assert [x.description for x in await store.list_open()] == ["참석자 목록 확정"]


async def test_closed_loops_are_closed_as_done(fx):
    store = InMemoryOpenLoopStore()
    target = await _open_loop(store, "핵심 메시지 3가지 구조화")
    keep = await _open_loop(store, "리뷰 답변")
    judge = CapturingJudge(LoopVerdict(closed_loops=["핵심 메시지 3가지 구조화"]))
    session = build_session(fx, CapturingEngine(), store, judge=judge)

    await say(session, "그거 하지 말라고")
    await say(session, "다시 한 번")

    assert (await store.get(target)).status == "done"
    assert [x.id for x in await store.list_open()] == [keep]


async def test_closed_loops_by_shown_number(fx):
    store = InMemoryOpenLoopStore()
    older = await _open_loop(store, "리뷰 답변", created_at=1)
    newer = await _open_loop(store, "분기 보고서 초안 제출", created_at=2)
    engine = CapturingEngine()
    session = build_session(fx, engine, store, judge=CapturingJudge(LoopVerdict(closed_loops=["1"])))

    await say(session, "보고서는 취소됐어")

    assert engine.requests[0].open_loops == ["[1] 분기 보고서 초안 제출", "[2] 리뷰 답변"]
    assert (await store.get(newer)).status == "done"
    assert (await store.get(older)).status == "open"


async def test_loop_closed_in_same_frame_is_not_reopened(fx):
    store = InMemoryOpenLoopStore()
    judge = CapturingJudge(
        LoopVerdict(
            open_loops=["내일 오후 3시까지 분기 보고서 초안을 팀장님께 보내야 해."],
            closed_loops=["분기 보고서 초안을 팀장님께 보내는 일정은 취소되었습니다."],
        )
    )
    session = build_session(fx, CapturingEngine(), store, judge=judge)

    await say(session, "분기 보고서 초안 팀장님께 보내는 건 취소됐어")

    assert await store.list_open() == []


async def test_user_cancel_closes_loop_without_model(fx):
    store = InMemoryOpenLoopStore()
    target = await _open_loop(store, "분기 보고서 초안 보냄")
    keep = await _open_loop(store, "리뷰 답변")
    session = build_session(fx, CapturingEngine(), store)

    await say(session, "분기 보고서 초안 보내는 건 취소됐어. 안 챙겨도 돼")

    assert (await store.get(target)).status == "dismissed"
    assert [x.id for x in await store.list_open()] == [keep]


async def test_due_suffix_saved_and_shown_back(fx):
    store = InMemoryOpenLoopStore()
    engine = CapturingEngine()
    judge = CapturingJudge(LoopVerdict(open_loops=["배포 결과 공유 회의 준비 @2099-10-12 10:00"]))
    session = build_session(fx, engine, store, judge=judge)

    await say(session, "내일 10시 배포 결과 공유 회의 준비해야 해")
    await say(session, "다음")

    [loop] = await store.list_open()
    assert loop.description == "배포 결과 공유 회의 준비"
    assert loop.due_ms == int(datetime(2099, 10, 12, 10, 0).timestamp() * 1000)
    # 남은 시간은 오늘 날짜에 따라 달라 앞부분만 본다
    [line] = engine.requests[1].open_loops
    assert line.startswith("[1] 배포 결과 공유 회의 준비 (기한 2099-10-12 10:00, ") and line.endswith("일 남음)")


async def test_expired_loops_closed_before_thought(fx):
    store = InMemoryOpenLoopStore()
    past = await _open_loop(store, "어제 회의 준비", due_ms=int(time.time() * 1000) - 7_200_000)
    await _open_loop(store, "리뷰 답변")
    engine = CapturingEngine()
    session = build_session(fx, engine, store, openloop_expiry=LoopExpiry(grace_ms=3_600_000, max_age_ms=0))

    await say(session, "안녕")

    assert (await store.get(past)).status == "expired"
    assert engine.requests[0].open_loops == ["[1] 리뷰 답변"]


async def test_agenda_changed_only_when_loops_change(fx):
    store = InMemoryOpenLoopStore()
    session = build_session(fx, None, store, judge=CapturingJudge(LoopVerdict(open_loops=["보고서 보내기"])))
    events: list = []

    async def sink(event) -> None:
        events.append(event)

    session.subscribe(sink)

    await say(session, "보고서 보내기로 했어")
    await say(session, "보고서 보내기 잊지 마")

    assert len([e for e in events if isinstance(e, AgendaChangedEvent)]) == 1
