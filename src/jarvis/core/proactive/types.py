"""[core] proactive 서브시스템이 주고받는 값(발화 메시지, 응답 계획, 게이팅 판정)."""

import uuid
from typing import Any, Literal
from pydantic import BaseModel, Field

from jarvis.agent_layer.thought.types import ProactiveAction


class ProactiveMessage(BaseModel):
    """시스템 → 사용자 비요청 발화. Push 채널(B2)이 운반하는 단위.

    kind:
    - filler    : Dual-Channel fast channel. "오래 걸림"을 알리는 즉답
    - proactive : daemon이 먼저 거는 말 (B3)
    - answer    : deferred 작업 완료 후의 실제 답(스트리밍이 아닌 단발 push 경로용)
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    text: str
    kind: Literal["filler", "proactive", "answer"] = "proactive"
    meta: dict[str, Any] = Field(default_factory=dict)


class ResponsePlan(BaseModel):
    """요청-기반 Dual-Channel 실행 계획.

    immediate : 현재 동작. 메인 루프를 그대로 수행(스트리밍).
    deferred  : fast channel로 filler 즉시 발화 후, slow channel(메인 루프)을
                백그라운드에서 수행.
    """

    mode: Literal["immediate", "deferred"] = "immediate"
    filler: str = ""  # deferred일 때 즉시 내보낼 holding 응답(오래 걸림을 표현)


class ProactiveDecision(BaseModel):
    """daemon 성찰 결과에 대한 게이팅 판정(B1).

    speak=True인 것만 사용자에게 노출한다. 행동은 위험도로 분리만 하고(Tier 1),
    실제 자율 실행/승인 연결은 후속 단계에서 채운다.
    """

    speak: bool = False
    message: str = ""
    reason: str = ""  # 판정 근거(관찰 가능성)
    autonomous_actions: list[ProactiveAction] = Field(default_factory=list)  # low risk
    approval_actions: list[ProactiveAction] = Field(default_factory=list)  # high risk
    # 응답 대기 게이트가 이번 판정에서 처음으로 "답 없이 오래 지남" 을 확인했다. 호출부가 약한 무시로 학습한다.
    ignored: bool = False
