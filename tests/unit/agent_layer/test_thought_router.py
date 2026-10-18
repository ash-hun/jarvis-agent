"""[agent_layer] router 판정: 학습 때와 같은 state, 대화에서 턴 짝 뽑기, 두 판정을 합치는 규칙."""

import pytest

from jarvis.agent_layer.thought.router import (
    ROUTE_CRITERIA,
    ROUTE_INSTRUCTIONS,
    RouteVerdict,
    ThoughtRouter,
    decide,
    recent_turns,
    route_state,
)
from jarvis.model_layer.types import AssistantMessage, TextContent, ToolResultMessage, UserMessage

OFFER = ("일본 여행 일정 짜줄래?", "4박 5일로 짜 드릴까요?")


def _assistant(text: str) -> AssistantMessage:
    return AssistantMessage(content=[TextContent(text=text)])


class FakeDecision:
    """state 별로 정한 확률을 돌려주고 받은 state 를 기록한다. None 이면 실패를 흉내 낸다."""

    def __init__(self, by_state: dict[str, float | None], default: float | None = 0.0) -> None:
        self._by_state = by_state
        self._default = default
        self.states: list[str] = []

    async def choice_probabilities(self, state, instructions, criteria):
        assert (instructions, criteria) == (ROUTE_INSTRUCTIONS, ROUTE_CRITERIA)
        self.states.append(state)
        p = self._by_state.get(state, self._default)
        return None if p is None else {"direct": 1 - p, "think": p}


def test_route_state_matches_training_layout():
    assert route_state("응 진행해", []) == "응 진행해"
    assert route_state("응 진행해", [OFFER]) == f"User: {OFFER[0]}\nAssistant: {OFFER[1]}\n\n응 진행해"
    turns = [("a", "1"), ("b", "2"), ("c", "3")]
    assert route_state("d", turns) == "User: b\nAssistant: 2\nUser: c\nAssistant: 3\n\nd"
    assert route_state("d", turns, context_turns=0) == "d"


def test_recent_turns_pairs_user_with_last_text_reply():
    history = [
        UserMessage(content="날씨 알려줘"),
        _assistant(""),  # 도구 호출만 있는 응답
        ToolResultMessage(tool_call_id="t1", tool_name="weather", content=[TextContent(text="맑음")]),
        _assistant("서울은 맑아요."),
        UserMessage(content="고마워"),
        UserMessage(content="그럼 내일은?"),
        _assistant("x" * 500),
    ]
    assert recent_turns(history) == [("날씨 알려줘", "서울은 맑아요."), ("그럼 내일은?", "x" * 400)]


@pytest.mark.parametrize(
    "p_values, expected",
    [
        ([0.1], RouteVerdict(think=False, p_think=0.1)),
        ([0.1, 0.25], RouteVerdict(think=True, p_think=0.25)),
        ([0.2], RouteVerdict(think=True, p_think=0.2)),  # 임계와 같으면 think
        ([0.9, None], RouteVerdict(think=True, p_think=None)),  # 하나라도 실패하면 사고를 놓치지 않게
        ([], RouteVerdict(think=True, p_think=None)),
    ],
)
def test_decide_takes_max_and_fails_toward_think(p_values, expected):
    assert decide(p_values, threshold=0.2) == expected


async def test_router_asks_once_without_history():
    decision = FakeDecision({"거실 불 꺼줘": 0.001})
    verdict = await ThoughtRouter(decision).route("거실 불 꺼줘", [])  # type: ignore[arg-type]
    assert decision.states == ["거실 불 꺼줘"]
    assert verdict == RouteVerdict(think=False, p_think=0.001)


async def test_router_catches_follow_up_that_needs_context():
    with_context = route_state("응 진행해", [OFFER])
    decision = FakeDecision({"응 진행해": 0.05, with_context: 0.6})
    history = [UserMessage(content=OFFER[0]), _assistant(OFFER[1])]
    verdict = await ThoughtRouter(decision).route("응 진행해", history)  # type: ignore[arg-type]
    assert sorted(decision.states) == sorted(["응 진행해", with_context])
    assert verdict == RouteVerdict(think=True, p_think=0.6)


async def test_router_failure_routes_to_think():
    verdict = await ThoughtRouter(FakeDecision({}, default=None)).route("아무 말", [])  # type: ignore[arg-type]
    assert verdict == RouteVerdict(think=True, p_think=None)
