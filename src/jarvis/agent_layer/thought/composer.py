from __future__ import annotations

from typing import Protocol, runtime_checkable

from jarvis.agent_layer.thought.types import ThoughtFrame


@runtime_checkable
class ThoughtComposer(Protocol):
    """
    `ThoughtFrame`을 메인 턴 프롬프트에 끼울 텍스트로 조립하는 전략.

    "사고를 어떻게 만들지"(프롬프트 템플릿)와 별개로, "만들어진 사고를 메인
    프롬프트에 어떻게 합칠지"를 교체 가능하게 분리한다. 빈 문자열을 반환하면
    아무것도 덧붙이지 않는다.
    """

    def compose(self, frame: ThoughtFrame) -> str: ...


class DefaultThoughtComposer:
    """기본 조립 — `ThoughtFrame.context_block()`을 그대로 사용(해석+회상 블록)."""

    def compose(self, frame: ThoughtFrame) -> str:
        return frame.context_block()


class InterpretationOnlyComposer:
    """해석 한 줄만 주입하는 경량 조립(회상/옵션 생략). 토큰 절약용 대안 예시."""

    def compose(self, frame: ThoughtFrame) -> str:
        if not frame.interpretation:
            return ""
        return f"[내적 사고] {frame.interpretation}"
