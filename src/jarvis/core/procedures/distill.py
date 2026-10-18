"""[core] 작업 구간을 LLM 으로 절차 초안(이름, 설명, 단계, 입력)으로 증류한다."""

import re
import json
from dataclasses import dataclass
from collections.abc import Awaitable, Callable

from jarvis.model_layer.types import LLMContext, ModelConfig, StreamOptions, UserMessage
from jarvis.core.procedures.detect import TaskSpan

MAX_NAME_LEN = 40
MAX_ARG_CHARS = 200  # 프롬프트에 싣는 도구 인자 길이. 파일 본문 같은 긴 값은 잘라도 절차는 읽힌다
MAX_OUTCOME_CHARS = 600
FALLBACK_NAME = "procedure"

PROMPT = """\
아래는 에이전트가 도구를 여러 번 호출해 성공적으로 끝낸 작업 기록이다.
같은 종류의 요청이 다시 왔을 때 그대로 따라 할 수 있는 "절차"로 일반화하라.
구체적인 파일명이나 값은 입력(parameters)으로 빼고, 단계는 어떤 도구를 어떤 순서로 왜 쓰는지 적어라.

JSON 객체 하나로만 답하라:
{{"name": "영문 소문자와 하이픈만 쓴 짧은 이름(예: run-tests-and-summarize)",
  "description": "이 절차가 하는 일 한 줄(한국어)",
  "parameters": "입력으로 받아야 하는 것 한 줄(없으면 빈 문자열)",
  "steps": ["1단계: 도구 이름과 목적", "2단계: ..."]}}

[사용자 요청]
{request}

[도구 호출 순서]
{steps}

[최종 결과]
{outcome}
"""


@dataclass(frozen=True)
class ProcedureDraft:
    name: str
    description: str
    steps: tuple[str, ...]
    parameters: str = ""


# 작업 구간 → 초안. 실패하면 None(호출자는 아무것도 쓰지 않는다).
Distiller = Callable[[TaskSpan], Awaitable[ProcedureDraft | None]]


def slugify(name: str) -> str:
    """도구 이름 규칙(영문, 숫자, 하이픈)에 맞춘다. 남는 게 없으면 FALLBACK_NAME."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:MAX_NAME_LEN].strip("-")
    return slug or FALLBACK_NAME


def parse_draft(raw: str) -> ProcedureDraft | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    raw_steps = data.get("steps")
    steps = [str(s).strip() for s in raw_steps if str(s).strip()] if isinstance(raw_steps, list) else []
    description = str(data.get("description", "")).strip()
    if not steps or not description:
        return None
    return ProcedureDraft(
        name=slugify(str(data.get("name", ""))),
        description=description,
        steps=tuple(steps),
        parameters=str(data.get("parameters", "")).strip(),
    )


def render_prompt(span: TaskSpan) -> str:
    lines = []
    for i, step in enumerate(span.steps, 1):
        args = json.dumps(step.args, ensure_ascii=False)
        if len(args) > MAX_ARG_CHARS:
            args = args[:MAX_ARG_CHARS] + "…"
        lines.append(f"{i}. {step.name} {args}")
    return PROMPT.format(request=span.request, steps="\n".join(lines), outcome=span.outcome[:MAX_OUTCOME_CHARS])


def llm_distiller(model: ModelConfig) -> Distiller:
    async def distill(span: TaskSpan) -> ProcedureDraft | None:
        from jarvis.model_layer.stream import stream_to_message

        ctx = LLMContext(messages=[UserMessage(content=render_prompt(span))], tools=None)
        result = await stream_to_message(model, ctx, StreamOptions())
        if result.error_message is not None:
            return None
        return parse_draft(result.text())

    return distill
