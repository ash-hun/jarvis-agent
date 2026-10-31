"""[agent_layer] ThoughtFrame 을 메인 턴 프롬프트에 끼울 텍스트로 조립하는 전략들을 둔다."""

from jarvis.agent_layer.thought.thought_types import ThoughtFrame


class ThoughtComposer:
    """
    `ThoughtFrame`을 메인 턴 프롬프트에 끼울 텍스트로 조립하는 전략의 기본 클래스.

    "사고를 어떻게 만들지"(프롬프트 템플릿)와 별개로, "만들어진 사고를 메인
    프롬프트에 어떻게 합칠지"를 교체 가능하게 분리한다. 빈 문자열을 반환하면
    아무것도 덧붙이지 않는다. 기본 조립은 `ThoughtFrame.context_block()`(해석+회상 블록)이다.
    """

    def compose(self, frame: ThoughtFrame) -> str:
        return frame.context_block()


class DefaultThoughtComposer(ThoughtComposer):
    """기본 조립: `ThoughtFrame.context_block()`을 그대로 사용(해석+회상 블록). 동작은 기본 클래스 그대로다."""


class InterpretationOnlyComposer(ThoughtComposer):
    """해석 한 줄만 주입하는 경량 조립(회상/옵션 생략). 토큰 절약용 대안 예시."""

    def compose(self, frame: ThoughtFrame) -> str:
        if not frame.interpretation:
            return ""
        return f"[내적 사고] {frame.interpretation}"
