"""openloop 세션 배선 테스트가 함께 쓰는 사고 엔진, AGENDA 판단 스텁과 세션 조립."""

from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.openloop.judge import LoopVerdict
from jarvis.core.session import AgentSession

SESSION_ID = "test-session"


class CapturingEngine:
    """프레임을 반환하고, 받은 ThoughtRequest를 기록하는 스텁."""

    def __init__(self, frame: ThoughtFrame | None = None) -> None:
        self._frame = frame or ThoughtFrame()
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


def build_session(fx: dict, engine, store, judge=None, **kwargs) -> AgentSession:
    return AgentSession(
        model=fx["model"],
        session_id=SESSION_ID,
        security_pipeline=fx["pipeline"],
        plugin_runner=fx["plugin_runner"],
        memory=fx["session_memory"],
        tool_registry=fx["tool_registry"],
        skill_registry=fx["skill_registry"],
        session_repo=fx["repo"],
        thought_engine=engine,
        openloop_store=store,
        loop_judge=judge or CapturingJudge(),
        **kwargs,
    )


async def say(session: AgentSession, text: str) -> None:
    """응답과 함께 도는 AGENDA 판단까지 끝낸다."""
    await session.prompt(text)
    await session.settle()
