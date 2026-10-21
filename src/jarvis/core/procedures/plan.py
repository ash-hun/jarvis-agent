"""[core] 절차의 실행 계획(도구와 인자 템플릿)을 읽고 검사하고 입력으로 채우는 순수 함수."""

import re
from typing import Any
from dataclasses import dataclass, field

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
# 절차가 절차를 부르면 끝없이 돌 수 있다. tool.TOOL_PREFIX 와 같은 값이다(순환 import 를 피해 여기 둔다)
PROCEDURE_PREFIX = "procedure_"


@dataclass(frozen=True)
class PlanStep:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)  # 문자열 값의 {{입력}} 자리를 호출 입력으로 채운다


def parse_plan(raw: object) -> tuple[PlanStep, ...]:
    """[{"tool": ..., "args": {...}}, ...] 꼴만 받는다. 하나라도 틀리면 계획 전체를 버린다.

    반쪽 계획을 실행하면 앞 단계의 부수효과만 남는다.
    """
    if not isinstance(raw, list):
        return ()
    steps: list[PlanStep] = []
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("tool") or "").strip():
            return ()
        args = item.get("args", {})
        if not isinstance(args, dict):
            return ()
        steps.append(PlanStep(tool=str(item["tool"]).strip(), args=dict(args)))
    return tuple(steps)


def placeholders(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(PLACEHOLDER_RE.findall(value))
    if isinstance(value, dict):
        return set().union(*(placeholders(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(placeholders(v) for v in value)) if value else set()
    return set()


def valid_plan(plan: tuple[PlanStep, ...], inputs: tuple[str, ...], tools: tuple[str, ...]) -> bool:
    """학습한 작업에서 실제로 쓴 도구만, 선언한 입력만 쓰고, 절차를 부르지 않는 계획."""
    return bool(plan) and all(
        step.tool in tools
        and not step.tool.startswith(PROCEDURE_PREFIX)
        and placeholders(step.args) <= set(inputs)
        for step in plan
    )


def fill(value: Any, values: dict[str, Any]) -> Any:
    """문자열 안의 {{입력}} 을 값으로 바꾼다. 문자열 전체가 자리 하나면 값의 타입을 지키려고 그대로 넣는다."""
    if isinstance(value, str):
        whole = PLACEHOLDER_RE.fullmatch(value.strip())
        if whole is not None:
            return values[whole.group(1)]
        return PLACEHOLDER_RE.sub(lambda m: str(values[m.group(1)]), value)
    if isinstance(value, dict):
        return {k: fill(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, values) for v in value]
    return value
