"""[agent_layer] router decision model 로 요청 턴마다 inner thought 를 돌릴지(think) 말지(direct) 정한다."""

import asyncio
from dataclasses import dataclass

from jarvis.model_layer.types import AssistantMessage, Message, UserMessage
from jarvis.model_layer.decision import DecisionModel

# router 가 학습한 질문 문구 그대로. 한 글자라도 바꾸면 학습 분포 밖이다
ROUTE_INSTRUCTIONS = "Should the assistant run inner thought on the last request, given the conversation before it?"
ROUTE_CRITERIA = {
    "direct": "No inner thought: the reply needs nothing worked out first. Small talk, a known fact, a single command "
    "or lookup, a one-step answer, or asking back when it is unclear what the user means.",
    "think": "Inner thought: a good reply needs working out first, in several steps. Calculation, planning, "
    "comparison, analysis, weighing sources, a judgement call, or long and creative writing.",
}
# 오프라인 평가(scripts/experiments/thought_router.py)에서 고른 값. 실사용 think 재현율 1.0, direct 재현율 0.68
ROUTE_THRESHOLD = 0.2
ROUTE_TIMEOUT_SEC = 1.0
CONTEXT_TURNS = 2
REPLY_CHARS = 400


@dataclass(frozen=True)
class RouteVerdict:
    think: bool
    p_think: float | None  # None 이면 router 가 답하지 못해 think 로 둔 것


def route_state(request: str, turns: list[tuple[str, str]], context_turns: int = CONTEXT_TURNS) -> str:
    """학습 때의 state 모양: 직전 턴(최대 두 개)을 User/Assistant 로 적고 빈 줄 뒤에 이번 요청."""
    recent = turns[-context_turns:] if context_turns else []
    earlier = "\n".join(f"User: {user}\nAssistant: {reply}" for user, reply in recent)
    return f"{earlier}\n\n{request}" if earlier else request


def recent_turns(history: list[Message], reply_chars: int = REPLY_CHARS) -> list[tuple[str, str]]:
    """사용자 말과 그 뒤 마지막 글 응답의 짝. 도구 결과와 글 없는 도구 호출은 router 가 학습하지 않았다."""
    turns: list[tuple[str, str]] = []
    user: str | None = None
    reply = ""
    for message in history:
        if isinstance(message, UserMessage):
            if user is not None and reply:
                turns.append((user, reply))
            user, reply = _text(message.content), ""
        elif isinstance(message, AssistantMessage) and message.text().strip():
            reply = message.text().strip()[:reply_chars]
    if user is not None and reply:
        turns.append((user, reply))
    return turns


def decide(p_values: list[float | None], threshold: float = ROUTE_THRESHOLD) -> RouteVerdict:
    """맥락 없는 판정과 맥락 있는 판정 중 큰 값으로 정한다. 하나라도 실패하면 사고를 놓치지 않게 think."""
    if not p_values or any(p is None for p in p_values):
        return RouteVerdict(think=True, p_think=None)
    p = max(p for p in p_values if p is not None)
    return RouteVerdict(think=p >= threshold, p_think=p)


class ThoughtRouter:
    """맥락을 넣으면 앞 주제를 따라가 화제가 바뀐 요청을 놓치고, 빼면 "응 진행해" 같은 후속 말을 놓친다. 둘 다 묻는다"""

    def __init__(self, decision: DecisionModel, threshold: float = ROUTE_THRESHOLD) -> None:
        self._decision = decision
        self._threshold = threshold

    async def route(self, user_input: str, history: list[Message]) -> RouteVerdict:
        turns = recent_turns(history)
        states = [route_state(user_input, turns, 0)]
        if turns:
            states.append(route_state(user_input, turns))
        answers = await asyncio.gather(
            *(self._decision.choice_probabilities(state, ROUTE_INSTRUCTIONS, ROUTE_CRITERIA) for state in states)
        )
        return decide([a["think"] if a is not None else None for a in answers], self._threshold)


def _text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(str(getattr(block, "text", "")) for block in content if getattr(block, "text", "")).strip()
    return ""
