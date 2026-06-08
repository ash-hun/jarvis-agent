"""
Inner Thought 서브시스템 — 요청 시점 메타인지 층.

메인 응답과 분리된 별도 LLM 호출로 구조화된 `ThoughtFrame`을 만들어
① 메인 턴 컨텍스트를 증강하고 ② 사고 로그/이벤트로 노출한다.

엔진은 `ThoughtEngine` Protocol 뒤에 격리되어 있어, 통째 교체(swap) 또는
`InnerThoughtEngine`의 seam 메서드 오버라이드로 독립 고도화할 수 있다.
"""

from __future__ import annotations

from jarvis.agent_layer.thought.composer import (
    DefaultThoughtComposer,
    InterpretationOnlyComposer,
    ThoughtComposer,
)
from jarvis.agent_layer.thought.engine import InnerThoughtEngine
from jarvis.agent_layer.thought.log import (
    THOUGHT_SOURCE,
    LTMThoughtSink,
    STMThoughtSink,
    ThoughtLog,
    ThoughtSink,
)
from jarvis.agent_layer.thought.prompt import (
    DEFAULT_TEMPLATE,
    ThoughtPromptTemplate,
)
from jarvis.agent_layer.thought.protocol import RecallFn, ThoughtEngine
from jarvis.agent_layer.thought.types import (
    ProactiveAction,
    ThoughtFrame,
    ThoughtRequest,
)

__all__ = [
    "DEFAULT_TEMPLATE",
    "DefaultThoughtComposer",
    "InnerThoughtEngine",
    "InterpretationOnlyComposer",
    "LTMThoughtSink",
    "ProactiveAction",
    "RecallFn",
    "STMThoughtSink",
    "THOUGHT_SOURCE",
    "ThoughtComposer",
    "ThoughtEngine",
    "ThoughtFrame",
    "ThoughtLog",
    "ThoughtPromptTemplate",
    "ThoughtRequest",
    "ThoughtSink",
]
