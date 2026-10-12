"""KAREN 이 청약 공고를 찾고 대출을 계산하는 흐름을 각본대로 흉내 내는 테스트용 프로바이더."""

import asyncio
import json
import re
from collections.abc import AsyncIterator

from jarvis.model_layer.types import (
    LLMContext,
    ModelConfig,
    StopEvent,
    StreamEvent,
    StreamOptions,
    TextDeltaEvent,
    ToolCallDeltaEvent,
    ToolResultMessage,
    Usage,
    UserMessage,
)

KAREN_MARK = "카렌"
LOAN_REQUEST = "공공분양 공고의 첫 주택형 평균분양가로 LTV 70%, 연 3.5%, 30년 원리금균등 계산"


def _text(message: UserMessage | ToolResultMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else "".join(getattr(c, "text", "") for c in content)


class HousingProvider:
    """시스템 프롬프트에 '카렌'이 있으면 KAREN, 없으면 JARVIS.

    - JARVIS 는 '신혼희망타운'을 받으면 ask_agent 로 KAREN 에게 맡긴다
    - KAREN 은 LH 목록 → 공공분양 공고 상세 → 그 공고 id 와 주택형으로 housing_loan 순서로 도구를 부른다.
      다음 인자는 앞 도구 결과 글에서 읽는다(실제 모델처럼 결과를 보고 고른다)
    - KAREN 은 'SH'를 받으면 sh_notice 목록 → 첫 글 상세
    - 도구가 오류면 오류를 그대로 알린다
    """

    provider_name = "housing"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        await asyncio.sleep(0.01)
        who = "karen" if KAREN_MARK in (context.system_prompt or "") else "main"
        last = context.messages[-1]
        step = self._karen(context, last) if who == "karen" else self._main(last)
        if step[0] == "say":
            self.calls.append((who, "say", {}))
            yield TextDeltaEvent(delta=step[1])
            yield StopEvent(reason="stop", usage=Usage(input=1, output=1))
            return
        _, tool, args = step
        self.calls.append((who, tool, args))
        yield ToolCallDeltaEvent(id=f"{who}-{len(self.calls)}", name=tool, arguments_delta=json.dumps(args))
        yield StopEvent(reason="tool_use", usage=Usage(input=1, output=1))

    def _main(self, last: object) -> tuple:
        if isinstance(last, ToolResultMessage):
            return ("say", "JARVIS 정리\n" + _text(last))
        if isinstance(last, UserMessage) and "신혼희망타운" in _text(last):
            message = f"신혼희망타운 공고중 공고를 찾고 {LOAN_REQUEST}"
            return ("tool", "ask_agent", {"agent": "karen", "message": message})
        return ("say", "네")

    def _karen(self, context: LLMContext, last: object) -> tuple:
        if isinstance(last, UserMessage):
            text = _text(last)
            if "신혼희망타운" in text:
                return ("tool", "lh_notice", {"category": "신혼희망타운", "status": "공고중"})
            if "SH" in text:
                return ("tool", "sh_notice", {"keyword": "행복주택"})
            return ("say", "네")
        if not isinstance(last, ToolResultMessage):
            return ("say", "네")
        result = _text(last)
        if last.is_error:
            return ("say", f"조회하지 못했습니다. {result}")
        if result.startswith("LH 청약 공고"):
            notice = re.search(r"id (\d+-\d+-39-39)", result)
            return ("tool", "lh_notice", {"id": notice.group(1)}) if notice else ("say", "공공분양 공고가 없습니다")
        if result.startswith("LH 공고 상세"):
            # 상세 끝의 안내대로 공고 id 와 주택형을 넘긴다. 금액은 도구가 공고에서 읽는다
            notice = re.search(r"notice_id=(\S+)", result)
            unit = re.search(r"\n(\d+)\.\d+([A-Z]) \|", result)
            args = {"notice_id": notice.group(1), "unit": f"{unit.group(1)}{unit.group(2)}", "ltv_percent": 70,
                    "annual_rate_percent": 3.5, "years": 30}
            return ("tool", "housing_loan", args)
        if result.startswith("SH 공고 (") and (seq := re.search(r"seq (\d+)", result)):
            return ("tool", "sh_notice", {"seq": seq.group(1)})
        # 마지막 도구 결과와, 앞선 상세 결과의 제목과 마감을 묶어 답한다
        earlier = [_text(m) for m in context.messages if isinstance(m, ToolResultMessage)]
        title = next((re.search(r"상세: (.+)", t).group(1) for t in earlier if "상세: " in t), "")
        deadline = next((re.search(r"마감\(KST [^)]+\): (\S+)", t).group(1) for t in earlier if "마감(KST" in t), "")
        head = f"{title} ({deadline})\n" if deadline else f"{title}\n"
        return ("say", "KAREN 정리: " + head + result)
