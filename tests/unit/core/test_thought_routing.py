"""router 배선: direct 는 사고 없이 답하고, think 는 사고를 응답과 함께 돌려 결과를 다음 턴에 한 번 넣는다."""

import pytest
import asyncio

from jarvis.agent_layer.agent_types import InnerThoughtEvent, ThoughtEndEvent, ThoughtRouteEvent
from jarvis.agent_layer.thought import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.router import RouteVerdict
from tests.fixtures.faux_provider import FauxProvider

FRAME = ThoughtFrame(interpretation="일정 충돌을 걱정한다", decision="silent", confidence=0.4)


class RecordingProvider(FauxProvider):
    """메인 응답 호출마다 받은 시스템 프롬프트를 남긴다."""

    def __init__(self) -> None:
        super().__init__(response="네")
        self.system_prompts: list[str | None] = []

    async def stream(self, model, context, options=None):
        self.system_prompts.append(context.system_prompt)
        async for event in super().stream(model, context, options):
            yield event


class GateEngine:
    """release 될 때까지 끝나지 않는 사고. 응답이 사고를 기다리지 않는지 본다."""

    def __init__(self, frame: ThoughtFrame | None = FRAME) -> None:
        self._frame = frame
        self.release = asyncio.Event()
        self.calls: list[ThoughtRequest] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        self.calls.append(request)
        await self.release.wait()
        return self._frame


class FixedRouter:
    def __init__(self, *verdicts: RouteVerdict) -> None:
        self._verdicts = list(verdicts)
        self.inputs: list[str] = []

    async def route(self, user_input, history) -> RouteVerdict:
        self.inputs.append(user_input)
        return self._verdicts.pop(0) if len(self._verdicts) > 1 else self._verdicts[0]


@pytest.fixture
def provider(monkeypatch) -> RecordingProvider:
    from jarvis.model_layer.model_registry import get_default_registry

    recording = RecordingProvider()
    monkeypatch.setitem(get_default_registry()._providers, "faux", recording)
    return recording


@pytest.fixture
async def build(
    faux_model, permissive_pipeline, plugin_runner, session_memory, tool_registry, skill_registry, jsonl_repo
):
    from jarvis.core.session import AgentSession

    await jsonl_repo.create(session_id="s")

    def _build(engine, router, timing: str = "race"):
        session = AgentSession(
            model=faux_model,
            session_id="s",
            security_pipeline=permissive_pipeline,
            plugin_runner=plugin_runner,
            memory=session_memory,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            session_repo=jsonl_repo,
            thought_engine=engine,
            thought_timing=timing,
            thought_router=router,
        )
        events: list = []

        async def sink(event) -> None:
            events.append(event)

        session.subscribe(sink)
        return session, events

    return _build


def _of(events: list, kind: type) -> list:
    return [e for e in events if isinstance(e, kind)]


async def test_direct_replies_without_thought(build, provider):
    engine = GateEngine()
    session, events = build(engine, FixedRouter(RouteVerdict(think=False, p_think=0.01)))

    assert await session.prompt("거실 불 꺼줘") is not None

    assert engine.calls == []
    assert [(e.think, e.p_think) for e in _of(events, ThoughtRouteEvent)] == [(False, 0.01)]
    assert _of(events, ThoughtEndEvent) == []


async def test_think_runs_beside_the_reply_and_feeds_the_next_turn_once(build, provider):
    engine = GateEngine()
    session, events = build(engine, FixedRouter(RouteVerdict(think=True, p_think=0.8)))

    # 사고가 끝나지 않았는데 응답이 먼저 끝난다
    await asyncio.wait_for(session.prompt("다음 주 일정 짜줘"), timeout=1.0)
    assert [c.user_input for c in engine.calls] == ["다음 주 일정 짜줘"]
    assert _of(events, ThoughtEndEvent) == []
    assert "[내적 사고]" not in (provider.system_prompts[0] or "")

    engine.release.set()
    await session.settle()
    assert [e.ok for e in _of(events, ThoughtEndEvent)] == [True]
    assert [e.interpretation for e in _of(events, InnerThoughtEvent)] == ["일정 충돌을 걱정한다"]

    await session.prompt("응 그렇게 해")
    await session.settle()
    await session.prompt("고마워")
    assert "일정 충돌을 걱정한다" in (provider.system_prompts[1] or "")
    # 다음 턴(둘째)도 think 라 사고가 다시 돌아 셋째 턴에 들어간다. 같은 프레임이 쌓이지 않고 하나만 들어간다
    assert (provider.system_prompts[2] or "").count("[내적 사고]") == 1


async def test_pending_thought_is_used_once(build, provider):
    engine = GateEngine()
    engine.release.set()
    router = FixedRouter(RouteVerdict(think=True, p_think=0.8), RouteVerdict(think=False, p_think=0.0))
    session, _ = build(engine, router)

    await session.prompt("일정 짜줘")
    await session.settle()
    await session.prompt("응")  # direct: 앞 사고 결과가 들어간다
    await session.prompt("고마워")  # direct: 이미 썼으니 비어 있다

    assert "[내적 사고]" in (provider.system_prompts[1] or "")
    assert "[내적 사고]" not in (provider.system_prompts[2] or "")


async def test_failed_thought_still_ends(build, provider):
    engine = GateEngine(frame=None)
    engine.release.set()
    session, events = build(engine, FixedRouter(RouteVerdict(think=True, p_think=None)))

    await session.prompt("분석해줘")
    await session.settle()
    await session.prompt("다음")

    assert [e.ok for e in _of(events, ThoughtEndEvent)][:1] == [False]
    assert "[내적 사고]" not in (provider.system_prompts[1] or "")


async def test_router_ignores_before_timing(build, provider):
    """router 가 있으면 request_timing 대신 router 가 정한다. before 여도 사고를 기다리지 않는다."""
    engine = GateEngine()
    session, _ = build(engine, FixedRouter(RouteVerdict(think=True, p_think=0.9)), timing="before")

    await asyncio.wait_for(session.prompt("비교해줘"), timeout=1.0)

    engine.release.set()
    await session.settle()


async def test_without_engine_router_is_not_asked(build, provider):
    router = FixedRouter(RouteVerdict(think=True, p_think=0.9))
    session, events = build(None, router)

    await session.prompt("안녕")

    assert router.inputs == []
    assert _of(events, ThoughtRouteEvent) == []
