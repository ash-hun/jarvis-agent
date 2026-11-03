"""[agent_layer] max_turns 를 다 쓰고도 도구를 부르던 루프를 정리하고 이어갈지 정하는 순수 함수."""

from typing import Literal

from jarvis.model_layer.model_types import AssistantMessage, Message, ToolResultMessage

# 넘침은 실패가 아니라 단계가 너무 컸다는 신호로 본다(EMMA 의 overflow decomposition).
# 한 번만 이어가고 두 번째면 정리문을 답으로 돌려준다. 같은 단계가 두 번 넘치면 잘게 나눠도 안 된다는 뜻이다
MAX_RESUMES = 1
# 정리문이 너무 길면 이어가는 차례마다 매번 붙어 입력을 키운다
SUMMARY_CHARS = 2_000
FALLBACK_STEPS = 12

# 두 번째 넘침이면 정리문이 그대로 사용자의 답이 된다. 이 문구가 한국어라 영어 요청에도 한국어 답이 나왔다
# (GAIA, KramaBench 실측). 항목 이름은 답을 찾는 쪽이 읽으므로 고정하고, 내용과 답은 원래 요청을 따르게 한다
SUMMARY_PROMPT = (
    "도구 호출 예산을 다 썼습니다. 도구를 더 부르지 말고 아래 형식으로만 짧게 정리해 주세요. "
    "항목 이름은 그대로 두고, 내용은 원래 요청과 같은 언어로 쓰세요.\n"
    "한 것: 지금까지 알아낸 사실과 결과(숫자, 경로, 이름은 그대로)\n"
    "남은 단계: 답을 내려면 아직 해야 할 일을 작은 단계로 나눠 차례대로\n"
    "지금까지의 답: 지금 알고 있는 것만으로 낼 수 있는 가장 나은 답. 원래 요청이 정한 답 형식을 그대로 따른다"
)
RESUME_DIRECTIVE = (
    "[이어가기] 앞선 시도가 도구 호출 예산을 다 썼습니다. 아래 정리의 남은 단계만 작은 단위로 진행하고, "
    "이미 한 일은 반복하지 마세요. 도구는 최대 {budget}번 더 쓸 수 있습니다. 다 되면 원래 요청과 같은 언어로, "
    "요청이 정한 답 형식대로 바로 답하세요.\n\n{summary}"
)
FALLBACK_HEADER = "도구 호출 예산을 다 써서 여기서 멈췄습니다. 지금까지 부른 도구:"

OverflowAction = Literal["resume", "answer"]


def exhausted(messages: list[Message]) -> bool:
    """마지막 차례가 도구를 실행하고 다음 차례를 기다리는 중에 예산이 끝났는가."""
    return bool(messages) and isinstance(messages[-1], ToolResultMessage)


def resume_budget(max_turns: int) -> int:
    """이어갈 차례 수. 원래 예산의 절반, 최소 한 차례."""
    return max(1, max_turns // 2)


def overflow_action(resumes_done: int) -> OverflowAction:
    return "resume" if resumes_done < MAX_RESUMES else "answer"


def clip_summary(text: str) -> str:
    text = text.strip()
    return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS].rstrip() + "…"


def resume_directive(summary: str, budget: int) -> str:
    return RESUME_DIRECTIVE.format(budget=budget, summary=clip_summary(summary))


def fallback_summary(messages: list[Message]) -> str:
    """정리 호출이 실패하거나 빈 답일 때 기록에서 부른 도구 이름만 모아 정리문을 만든다."""
    names = [c.name for m in messages if isinstance(m, AssistantMessage) for c in m.tool_calls()]
    if not names:
        return FALLBACK_HEADER.rstrip(":") + "."
    shown = names[-FALLBACK_STEPS:]
    skipped = len(names) - len(shown)
    lead = f"(앞의 {skipped}번 생략) " if skipped else ""
    return f"{FALLBACK_HEADER} {lead}{', '.join(shown)}"
