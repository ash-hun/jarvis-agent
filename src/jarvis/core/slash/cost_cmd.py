"""[core] 현재 세션의 모델별 토큰 사용량과 추정 비용을 보고하는 /cost 핸들러 factory."""

from typing import TYPE_CHECKING, cast
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.model_layer.types import AssistantMessage, Usage
    from jarvis.agent_layer.session.protocol import SessionRepo

Handler = Callable[[str], Awaitable[str]]

# 모델명 substring → (입력, 출력) USD per 1M tokens. 순서 중요 (gpt-4o-mini가 gpt-4o보다 먼저).
# ui/web/static/app.js getCostRate()와 동기화.
_COST_RATES: list[tuple[str, float, float]] = [
    ("opus", 15.0, 75.0),
    ("sonnet", 3.0, 15.0),
    ("haiku", 0.8, 4.0),
    ("gpt-4o-mini", 0.15, 0.6),
    ("gpt-4o", 5.0, 15.0),
    ("gemini", 1.25, 5.0),
]
_DEFAULT_RATE = (3.0, 15.0)


def cost_rate(model: str) -> tuple[float, float]:
    """모델명으로 (입력, 출력) per-1M 단가를 반환. 매칭 없으면 기본값."""
    m = (model or "").lower()
    for needle, rate_in, rate_out in _COST_RATES:
        if needle in m:
            return rate_in, rate_out
    return _DEFAULT_RATE


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """입력/출력 토큰 수로 추정 비용(USD)을 계산한다."""
    rate_in, rate_out = cost_rate(model)
    return input_tokens / 1e6 * rate_in + output_tokens / 1e6 * rate_out


def make_cost_handler(session_repo: "SessionRepo", session_id: str = "default") -> Handler:
    """/cost 핸들러 factory. 현재(기본) 세션의 누적 사용량을 모델별로 집계."""

    async def handle(_args: str) -> str:
        messages = await session_repo.get_messages(session_id)
        # 모델별 Usage 집계
        per_model: dict[str, dict[str, int]] = {}
        for msg in messages:
            if getattr(msg, "role", None) != "assistant":
                continue
            # role 로 거른 뒤라 assistant 메시지다. isinstance 로 바꾸면 role 만 맞춘 테스트 더블이 빠진다
            assistant = cast("AssistantMessage", msg)
            usage: Usage = assistant.usage
            model = assistant.model or "(unknown)"
            agg = per_model.setdefault(
                model, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
            )
            agg["input"] += usage.input
            agg["output"] += usage.output
            agg["cache_read"] += usage.cache_read
            agg["cache_write"] += usage.cache_write

        if not per_model:
            return "[Cost] 집계할 사용량이 없습니다."

        lines = [f"[Cost] 세션 '{session_id}' 사용량"]
        total_in = total_out = total_cr = 0
        total_cost = 0.0
        for model in sorted(per_model):
            a = per_model[model]
            cost = estimate_cost(model, a["input"], a["output"])
            total_in += a["input"]
            total_out += a["output"]
            total_cr += a["cache_read"]
            total_cost += cost
            lines.append(
                f"  {model}\n"
                f"    입력 {a['input']:,} · 출력 {a['output']:,} · "
                f"캐시읽기 {a['cache_read']:,} → ${cost:.4f}"
            )

        lines.append(
            f"  ─\n"
            f"  합계: 입력 {total_in:,} · 출력 {total_out:,} · "
            f"캐시읽기 {total_cr:,} · 추정 비용 ${total_cost:.4f}"
        )
        return "\n".join(lines)

    return handle
