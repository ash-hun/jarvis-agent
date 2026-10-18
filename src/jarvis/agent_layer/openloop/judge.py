"""[agent_layer] 매 요청 턴에 새로 생긴 약속과 끝난 약속을 가려내는 AGENDA 판단(별도 LLM 호출)."""

from typing import Any
from datetime import datetime
from collections.abc import Callable
from pydantic import BaseModel, Field, ValidationError, field_validator

from jarvis.model_layer.types import LLMContext, Message, ModelConfig, StreamOptions, UserMessage
from jarvis.agent_layer.thought.engine import HISTORY_CHARS, extract_json, format_history
from jarvis.agent_layer.thought.types import items_to_text
from jarvis.model_layer.stream import stream_to_message
from jarvis.common.logger import get_logger

# 약속은 이번 입력에서만 잡고, 닫을지는 직전 맥락만 있으면 된다. 사고보다 짧게 본다
JUDGE_HISTORY_TURNS = 4
JUDGE_PROMPT = """\
너는 Jarvis 의 AGENDA 판단 모듈이다. 사용자에게 직접 답하지 않는다.
아래 입력을 보고 JSON 객체 하나만 출력하라. JSON 외 다른 텍스트는 금지한다.

[지금] {{now}}
[열린 약속] {{open_loops}}
[최근 대화] {{history}}
[사용자 입력] {{user_input}}

다음 키를 가진 JSON 객체 하나만 출력하라:
- open_loops (string[]): [사용자 입력]에서 사용자가 새로 흘린 약속·미완 작업·나중에
    챙길 일을 짧게 적어라(예: "내일 배포 후 결과 공유하기"). [사용자 입력]에 직접 나온
    것만 적고, [최근 대화]나 [열린 약속]에서 옮겨 적지 마라. [열린 약속]에 이미 있는
    것과 같은 뜻이면 다시 적지 마라. 사용자가 그만두라고 한 일은 적지 마라.
    날짜나 시각이 나오면 [지금]을 기준으로 계산해 끝에 " @YYYY-MM-DD HH:MM" 을 꼭 붙여라.
    예: [지금]이 2026-10-11T22:00 이고 "내일 오후 3시까지 보고서 보내기" 면
    "보고서 보내기 @2026-10-12 15:00". 맨 끝에는 그 약속이 나온 [사용자 입력]의 구절을
    고치지 말고 그대로 옮겨 " (근거: ...)" 로 붙여라.
    예: "보고서 보내기 @2026-10-12 15:00 (근거: 내일 오후 3시까지 보고서 보내야 해)".
    없으면 빈 배열.
- closed_loops (string[]): [열린 약속]의 항목 중 [사용자 입력]으로 끝났거나, 사용자가
    하지 말라고 했거나, 취소된 것의 번호만 적어라(예: [2] 가 취소됐으면 ["2"]).
    [열린 약속]에 없는 것은 적지 마라. 새로 생긴 약속은 여기가 아니라 open_loops 에
    적는다. 없으면 빈 배열.
"""

logger = get_logger(__name__)


class LoopVerdict(BaseModel):
    open_loops: list[str] = Field(default_factory=list)
    closed_loops: list[str] = Field(default_factory=list)

    @field_validator("open_loops", "closed_loops", mode="before")
    @classmethod
    def _items_to_text(cls, value: Any) -> Any:
        return items_to_text(value)


LOOP_SCHEMA = LoopVerdict.model_json_schema()


def render_prompt(now: datetime, user_input: str, open_loops: list[str], history: list[Message]) -> str:
    values = {
        "now": now.isoformat(timespec="seconds"),
        "open_loops": "\n".join(f"- {x}" for x in open_loops),
        "history": format_history(history, JUDGE_HISTORY_TURNS, HISTORY_CHARS),
        "user_input": user_input,
    }
    out = JUDGE_PROMPT
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def parse_verdict(raw: str) -> LoopVerdict | None:
    payload = extract_json(raw)
    if payload is None:
        return None
    try:
        return LoopVerdict.model_validate(payload)
    except ValidationError:
        return None


class OpenLoopJudge:
    """사고와 따로 매 턴 돈다. router 가 사고를 건너뛴 턴(direct)의 약속도 AGENDA 에 남기기 위해서다."""

    def __init__(self, model: ModelConfig, clock: Callable[[], datetime] | None = None) -> None:
        self._model = model
        self._clock = clock or datetime.now

    async def judge(self, user_input: str, open_loops: list[str], history: list[Message]) -> LoopVerdict | None:
        """판단에 실패하면 None. 약속 추적은 부가 기능이라 턴을 막지 않는다."""
        prompt = render_prompt(self._clock(), user_input, open_loops, history)
        try:
            ctx = LLMContext(messages=[UserMessage(content=prompt)], tools=None)
            raw = (await stream_to_message(self._model, ctx, StreamOptions(json_schema=LOOP_SCHEMA))).text()
        except Exception as exc:
            logger.info(f"[Agenda] judge call failed: {exc!r}")
            return None
        verdict = parse_verdict(raw)
        if verdict is None:
            logger.info(f"[Agenda] judge output unparsable (len={len(raw)}): {raw[-200:]!r}")
        return verdict
