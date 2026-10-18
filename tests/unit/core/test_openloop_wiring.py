"""Open-loop session 배선: AGENDA 판단이 감지한 약속의 저장과 닫기, 사고에 열린 약속 주입."""
import time
import pytest
from datetime import datetime

from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, LoopExpiry, OpenLoop
from jarvis.agent_layer.thought.types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.openloop.judge import LoopVerdict
from jarvis.core.proactive import DefaultProactivityCore


class CapturingEngine:
    """프레임을 반환하고, 받은 ThoughtRequest를 기록하는 스텁."""

    def __init__(self, frame: ThoughtFrame) -> None:
        self._frame = frame
        self.requests: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.requests.append(request)
        return self._frame


class CapturingJudge:
    """판단 결과를 돌려주고, 받은 입력과 보여준 열린 약속을 기록하는 스텁."""

    def __init__(self, verdict: LoopVerdict | None = None) -> None:
        self._verdict = verdict or LoopVerdict()
        self.calls: list[tuple[str, list[str]]] = []

    async def judge(self, user_input, open_loops, history) -> LoopVerdict | None:
        self.calls.append((user_input, open_loops))
        return self._verdict


def _build_session(
    fx, engine, store, user_model_store=None, proactivity_factory=None, openloop_expiry=None, judge=None
):
    from jarvis.core.session import AgentSession

    return AgentSession(
        model=fx["model"],
        session_id="test-session",
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
        thought_engine=engine,
        openloop_store=store,
        openloop_expiry=openloop_expiry,
        user_model_store=user_model_store,
        proactivity_factory=proactivity_factory,
        loop_judge=judge or CapturingJudge(),
    )


async def _say(session, text: str) -> None:
    """응답과 함께 도는 AGENDA 판단까지 끝낸다."""
    await session.prompt(text)
    await session.settle()


@pytest.fixture
def fx(
    faux_model,
    permissive_pipeline,
    plugin_runner,
    session_memory,
    tool_registry,
    skill_registry,
    jsonl_repo,
):
    return {
        "model": faux_model,
        "pipeline": permissive_pipeline,
        "plugin_runner": plugin_runner,
        "session_memory": session_memory,
        "tool_registry": tool_registry,
        "skill_registry": skill_registry,
        "repo": jsonl_repo,
    }


@pytest.mark.asyncio
async def test_detected_open_loops_are_persisted(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(open_loops=["내일 배포 결과 공유", "리뷰 답변"]))
    session = _build_session(fx, engine, store, judge=judge)

    await _say(session, "내일 배포 결과 공유하고 리뷰 답변도 할게")

    loops = await store.list_open(session_id="test-session")
    descs = {x.description for x in loops}
    assert descs == {"내일 배포 결과 공유", "리뷰 답변"}
    assert all(x.origin_session == "test-session" for x in loops)


@pytest.mark.asyncio
async def test_open_loops_carry_session_agent(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    judge = CapturingJudge(LoopVerdict(open_loops=["뉴스 정리"]))
    session = _build_session(fx, CapturingEngine(ThoughtFrame()), store, judge=judge)
    session.agent_name = "karen"

    await _say(session, "뉴스 정리해 줄게")

    assert [x.agent_id for x in await store.list_open(session_id="test-session")] == ["karen"]


@pytest.mark.asyncio
async def test_open_loops_deduped_across_turns(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(open_loops=["같은 약속"]))
    session = _build_session(fx, engine, store, judge=judge)

    await _say(session, "같은 약속 첫 턴")
    await _say(session, "같은 약속 둘째 턴")  # 같은 open_loop 재감지

    assert len(await store.list_open()) == 1  # 중복 저장 안 됨


@pytest.mark.asyncio
async def test_existing_open_loops_recalled_into_request(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    await store.add(OpenLoop(description="기존 약속 A", origin_session="test-session"))
    engine = CapturingEngine(ThoughtFrame())
    session = _build_session(fx, engine, store)

    await _say(session, "새 입력")

    # 엔진에 전달된 ThoughtRequest.open_loops에 기존 항목이 번호와 함께 주입됐다.
    assert engine.requests[0].open_loops == ["[1] 기존 약속 A"]


@pytest.mark.asyncio
async def test_no_store_is_noop(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(open_loops=["무시됨"]))
    session = _build_session(fx, engine, store=None, judge=judge)

    result = await session.prompt("입력")
    assert result is not None  # store 없어도 정상 동작
    assert engine.requests[0].open_loops == []


@pytest.mark.asyncio
async def test_user_model_injected_into_request(fx):
    from jarvis.agent_layer.usermodel import InMemoryUserModelStore, UserModel

    await fx["repo"].create(session_id="test-session")
    um_store = InMemoryUserModelStore()
    await um_store.save(UserModel(summary="간결한 답 선호", traits=["Python"]))
    engine = CapturingEngine(ThoughtFrame())
    session = _build_session(fx, engine, store=None, user_model_store=um_store)

    await _say(session, "새 입력")

    injected = engine.requests[0].user_model
    assert "[사용자 모델]" in injected
    assert "간결한 답 선호" in injected and "Python" in injected


@pytest.mark.asyncio
async def test_user_model_absent_is_blank(fx):
    await fx["repo"].create(session_id="test-session")
    engine = CapturingEngine(ThoughtFrame())
    session = _build_session(fx, engine, store=None, user_model_store=None)

    await _say(session, "입력")
    assert engine.requests[0].user_model == ""


@pytest.mark.asyncio
async def test_reflection_does_not_persist_open_loops(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    await store.add(OpenLoop(description="참석자 목록 확정", origin_session="test-session"))
    # 성찰이 기존 약속을 바꿔 말해도 새 항목으로 쌓이면 안 된다.
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(open_loops=["참석자들의 최종 리스트 확정"]))
    session = _build_session(
        fx, engine, store, proactivity_factory=lambda emit: DefaultProactivityCore(emit_proactive=emit), judge=judge
    )

    await session.reflect()

    assert engine.requests[0].mode == "reflection"
    assert judge.calls == []  # AGENDA 판단은 사용자 입력이 있는 턴에만 돈다
    assert [x.description for x in await store.list_open()] == ["참석자 목록 확정"]


@pytest.mark.asyncio
async def test_closed_loops_are_closed_as_done(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    target = await store.add(OpenLoop(description="핵심 메시지 3가지 구조화", origin_session="test-session"))
    keep = await store.add(OpenLoop(description="리뷰 답변", origin_session="test-session"))
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(closed_loops=["핵심 메시지 3가지 구조화"]))
    session = _build_session(fx, engine, store, judge=judge)

    await _say(session, "그거 하지 말라고")
    await _say(session, "다시 한 번")  # 이미 닫힌 건 다시 건드리지 않는다

    assert (await store.get(target)).status == "done"
    assert [x.id for x in await store.list_open()] == [keep]


@pytest.mark.asyncio
async def test_due_suffix_saved_and_shown_back(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(open_loops=["배포 결과 공유 회의 준비 @2099-10-12 10:00"]))
    session = _build_session(fx, engine, store, judge=judge)

    await _say(session, "내일 10시 배포 결과 공유 회의 준비해야 해")
    await _say(session, "다음")

    [loop] = await store.list_open()
    assert loop.description == "배포 결과 공유 회의 준비"
    assert loop.due_ms == int(datetime(2099, 10, 12, 10, 0).timestamp() * 1000)
    assert engine.requests[1].open_loops == ["[1] 배포 결과 공유 회의 준비 (기한 2099-10-12 10:00)"]


@pytest.mark.asyncio
async def test_expired_loops_closed_before_thought(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    now_ms = int(time.time() * 1000)
    past = await store.add(
        OpenLoop(description="어제 회의 준비", due_ms=now_ms - 7_200_000, origin_session="test-session")
    )
    await store.add(OpenLoop(description="리뷰 답변", origin_session="test-session"))
    engine = CapturingEngine(ThoughtFrame())
    session = _build_session(fx, engine, store, openloop_expiry=LoopExpiry(grace_ms=3_600_000, max_age_ms=0))

    await _say(session, "안녕")

    assert (await store.get(past)).status == "expired"
    assert engine.requests[0].open_loops == ["[1] 리뷰 답변"]


@pytest.mark.asyncio
async def test_reflection_does_not_close_loops(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    await store.add(OpenLoop(description="참석자 목록 확정", origin_session="test-session"))
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(closed_loops=["참석자 목록 확정"]))
    session = _build_session(
        fx, engine, store, proactivity_factory=lambda emit: DefaultProactivityCore(emit_proactive=emit), judge=judge
    )

    await session.reflect()

    assert judge.calls == []
    assert [x.description for x in await store.list_open()] == ["참석자 목록 확정"]


@pytest.mark.asyncio
async def test_closed_loops_by_shown_number(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    older = await store.add(OpenLoop(description="리뷰 답변", origin_session="test-session", created_at=1))
    newer = await store.add(OpenLoop(description="분기 보고서 초안 제출", origin_session="test-session", created_at=2))
    # 최신순으로 [1] 분기 보고서, [2] 리뷰 답변 이 보인다
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(closed_loops=["1"]))
    session = _build_session(fx, engine, store, judge=judge)

    await _say(session, "보고서는 취소됐어")

    assert engine.requests[0].open_loops == ["[1] 분기 보고서 초안 제출", "[2] 리뷰 답변"]
    assert (await store.get(newer)).status == "done"
    assert (await store.get(older)).status == "open"


@pytest.mark.asyncio
async def test_open_loops_not_in_input_are_dropped(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    # 회상된 기억 속 약속을 새로 흘린 것처럼 옮겨 적은 경우
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(LoopVerdict(open_loops=["핵심 메시지 3가지 구조화 작업", "분기 보고서 초안 제출"]))
    session = _build_session(fx, engine, store, judge=judge)

    await _say(session, "내일까지 분기 보고서 초안 보내야 해")

    assert [x.description for x in await store.list_open()] == ["분기 보고서 초안 제출"]


@pytest.mark.asyncio
async def test_loop_closed_in_same_frame_is_not_reopened(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    engine = CapturingEngine(ThoughtFrame())
    judge = CapturingJudge(
        LoopVerdict(
            open_loops=["내일 오후 3시까지 분기 보고서 초안을 팀장님께 보내야 해."],
            closed_loops=["분기 보고서 초안을 팀장님께 보내는 일정은 취소되었습니다."],
        )
    )
    session = _build_session(fx, engine, store, judge=judge)

    await _say(session, "분기 보고서 초안 팀장님께 보내는 건 취소됐어")

    assert await store.list_open() == []


@pytest.mark.asyncio
async def test_user_cancel_closes_loop_without_model(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    target = await store.add(OpenLoop(description="분기 보고서 초안 보냄", origin_session="test-session"))
    keep = await store.add(OpenLoop(description="리뷰 답변", origin_session="test-session"))
    engine = CapturingEngine(ThoughtFrame())  # 사고가 closed_loops 를 놓친 경우
    session = _build_session(fx, engine, store)

    await _say(session, "분기 보고서 초안 보내는 건 취소됐어. 안 챙겨도 돼")

    assert (await store.get(target)).status == "dismissed"
    assert [x.id for x in await store.list_open()] == [keep]


@pytest.mark.asyncio
async def test_judge_sees_numbered_open_loops(fx):
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    await store.add(OpenLoop(description="리뷰 답변", origin_session="test-session"))
    judge = CapturingJudge()
    session = _build_session(fx, CapturingEngine(ThoughtFrame()), store, judge=judge)

    await _say(session, "리뷰 답변 끝냈어")

    assert judge.calls == [("리뷰 답변 끝냈어", ["[1] 리뷰 답변"])]


@pytest.mark.asyncio
async def test_open_loops_are_tracked_without_thought(fx):
    """router 가 사고를 건너뛴 턴(direct)처럼 사고 엔진이 돌지 않아도 약속은 AGENDA 에 남는다."""
    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    judge = CapturingJudge(LoopVerdict(open_loops=["보고서 보내기"]))
    session = _build_session(fx, None, store, judge=judge)

    await _say(session, "내일까지 보고서 보내기로 했어")

    assert [x.description for x in await store.list_open()] == ["보고서 보내기"]


@pytest.mark.asyncio
async def test_agenda_changed_only_when_loops_change(fx):
    """화면은 이 신호로 AGENDA 를 다시 읽는다. 같은 약속을 다시 잡아 바뀐 게 없으면 보내지 않는다."""
    from jarvis.agent_layer.types import AgendaChangedEvent

    await fx["repo"].create(session_id="test-session")
    store = InMemoryOpenLoopStore()
    judge = CapturingJudge(LoopVerdict(open_loops=["보고서 보내기"]))
    session = _build_session(fx, None, store, judge=judge)
    events: list = []

    async def sink(event) -> None:
        events.append(event)

    session.subscribe(sink)

    await _say(session, "보고서 보내기로 했어")
    await _say(session, "보고서 보내기 잊지 마")

    assert len([e for e in events if isinstance(e, AgendaChangedEvent)]) == 1
