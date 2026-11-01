"""[core] 실패한 턴 묶음을 reflector LLM 에 보여 범위 하나와 수정 하나(Reflection)를 받는다."""

import json
from typing import Literal
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamOptions, UserMessage

SCOPE_SLIP = "execution_slip"
SCOPE_BEHAVIOR = "agent_behavior"
SCOPE_PROCEDURE = "procedure"
ACTION_NONE = "no_change"
ACTION_PROCEDURE = "revise_procedure"
ACTION_PATTERN = "task_pattern"
# 범위마다 허락된 행동 하나. 틀린 층에 쓴 교훈은 다시 쓰이지 않거나 무관한 작업을 오염시킨다
# ponytail: EMMA 의 routing, missing_capability 범위는 없다, 컨트롤러 기억과 에이전트 자동 생성이 생기면 더한다
SCOPE_ACTIONS = {SCOPE_SLIP: ACTION_NONE, SCOPE_BEHAVIOR: ACTION_PATTERN, SCOPE_PROCEDURE: ACTION_PROCEDURE}
MAX_REQUEST_CHARS = 2000  # 실패한 요청 하나를 프롬프트에 싣는 길이
MAX_ANSWER_CHARS = 800
MAX_PROCEDURE_CHARS = 1500

PROMPT = (
    "에이전트가 아래 작업 종류에서 실패했다. 실패 기록을 보고 어느 범위의 문제인지 하나를 고르고, 그"
    " 범위 안에서 수정 하나만 제안하라.\n"
    "\n"
    "범위와 행동(반드시 짝을 맞춘다):\n"
    "- execution_slip: 방법은 알았는데 한 번 실수했다(잘못 읽음, 계산 실수, 일시 오류). 되풀이되지"
    " 않는다 -> no_change\n"
    "- agent_behavior: 주제와 무관하게 되풀이될 작업 습관이 틀렸다(입력을 끝까지 읽지 않음, 검증하지"
    " 않음, 요청한 형식을 무시함, 계산 전에 답함) -> task_pattern\n"
    "- procedure: 이 종류의 작업을 푸는 방법(알고리즘, 규칙, 순서, 형식 규약)이 틀렸거나 없다 ->"
    " revise_procedure\n"
    "\n"
    "규칙:\n"
    "- 일반화한다. 이번 작업의 고유한 값, 이름, 정답을 쓰지 않고 입력 문장을 그대로 베끼지 않는다. 같은"
    " 종류의 다음 작업 모두에 통해야 한다.\n"
    "- 가장 작은 수정 하나. content 는 1500자 이하.\n"
    "- revise_procedure: 현재 절차가 있으면 고친 전체 절차를, 없으면 새 절차를 단계 목록으로 content 에"
    " 쓴다.\n"
    "- task_pattern: when(어떤 요청일 때), content(어떻게), keywords(그런 요청에 들어갈 낱말 2~6개)를"
    " 쓴다.\n"
    "\n"
    "JSON 객체 하나로만 답하라:\n"
    '{{"diagnosis": "무엇이 틀렸는지 한두 문장", "scope": "execution_slip | agent_behavior | procedure",\n'
    '  "action": "no_change | task_pattern | revise_procedure", "name": "영문 소문자와 하이픈만 쓴 짧은'
    ' 이름",\n'
    '  "when": "어떤 요청일 때", "content": "고친 방법(문자열, 단계는 줄바꿈으로 나눈다)", "keywords":'
    ' ["..."]}}\n'
    "\n"
    "[작업 종류]\n"
    "{task_type}\n"
    "\n"
    "[현재 절차]\n"
    "{procedure}\n"
    "\n"
    "[실패 기록]\n"
    "{attempts}\n"
    "{refusal}"
)

REFUSAL = (
    "\n[직전 제안이 거부된 이유]\n{reason}\n"
    "이유를 고쳐 다시 제안하라. 고칠 수 없으면 execution_slip, no_change 로 답한다.\n"
)


class Reflection(BaseModel):
    """reflector 출력. 모르는 필드는 버린다. 값의 허용 범위는 거름망(update_guard)이 본다."""

    model_config = ConfigDict(extra="ignore")

    scope: Literal["execution_slip", "agent_behavior", "procedure"]
    action: Literal["no_change", "revise_procedure", "task_pattern"]
    diagnosis: str = ""
    name: str = Field(default="", max_length=200)
    when: str = ""
    content: str = ""
    keywords: list[str] = Field(default_factory=list)

    @field_validator("content", mode="before")
    @classmethod
    def _lines(cls, value: object) -> object:
        """단계 목록을 배열로 내는 모델이 많다. 줄 단위 글로 받는다."""
        return "\n".join(str(v) for v in value) if isinstance(value, list) else value

    @field_validator("keywords", mode="before")
    @classmethod
    def _split(cls, value: object) -> object:
        return [k for k in value.split(",")] if isinstance(value, str) else value


@dataclass(frozen=True)
class Attempt:
    request: str
    answer: str
    overflow: bool = False  # 도구 반복 예산을 다 쓴 턴. 단계가 너무 컸다는 근거다


@dataclass(frozen=True)
class FailureCase:
    agent_id: str
    task_type: str
    attempts: tuple[Attempt, ...]
    procedure: str = ""  # 이 작업 종류의 지금 절차 본문. 없으면 빈 문자열
    references: tuple[str, ...] = ()  # 판정에 쓴 정답. 있으면 거름망이 수정에 정답이 들어갔는지 본다


# (실패 묶음, 직전 거부 이유) → 제안. 거부 이유는 첫 시도에서 빈 문자열이다. 출력을 못 읽으면 None
Reflector = Callable[[FailureCase, str], Awaitable[Reflection | None]]


def parse_reflection(raw: str) -> Reflection | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return Reflection.model_validate(json.loads(raw[start : end + 1]))
    except (json.JSONDecodeError, ValidationError):
        return None


def render_prompt(case: FailureCase, refusal: str = "") -> str:
    lines: list[str] = []
    for i, a in enumerate(case.attempts, 1):
        lines.append(f"{i}. 요청: {a.request[:MAX_REQUEST_CHARS]}")
        lines.append(f"   답: {a.answer[:MAX_ANSWER_CHARS]}")
        if a.overflow:
            lines.append("   (넘침: 도구 반복 예산을 다 써서 정리하고 이어갔다. 한 단계가 너무 컸다는 근거다)")
    return PROMPT.format(
        task_type=case.task_type,
        procedure=case.procedure[:MAX_PROCEDURE_CHARS] or "(없음)",
        attempts="\n".join(lines),
        refusal=REFUSAL.format(reason=refusal) if refusal else "",
    )


def llm_reflector(model: ModelConfig) -> Reflector:
    async def reflect(case: FailureCase, refusal: str) -> Reflection | None:
        from jarvis.model_layer.stream import stream_to_message

        ctx = LLMContext(messages=[UserMessage(content=render_prompt(case, refusal))], tools=None)
        result = await stream_to_message(model, ctx, StreamOptions())
        if result.error_message is not None:
            return None
        return parse_reflection(result.text())

    return reflect
