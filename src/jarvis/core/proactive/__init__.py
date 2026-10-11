"""[core] Proactive 서브시스템(Tier 1) 패키지. 요청 없이도 먼저 행동하고 말을 거는 코어를 묶는다."""

# 두 트리거를 같은 정책(B1)과 Push 채널(B2)로 다룬다:
# - 요청-기반 Dual-Channel: 오래 걸릴 작업이면 filler 즉시 발화 후 백그라운드 수행
# - 자율 proactive: daemon이 성찰해 먼저 말 검 (B3)
# 코어는 `ProactivityCore` 기본 클래스 뒤에 격리되어 통째 교체/커스텀 가능하다.

from __future__ import annotations

from jarvis.core.proactive.core import (
    DefaultProactivityCore,
    EmitProactive,
    ProactivityCore,
    RunMain,
)
from jarvis.core.proactive.daemon import (
    ProactivityDaemon,
    ReflectOnce,
    ReflectTargets,
)
from jarvis.core.proactive.feedback import FeedbackLearner
from jarvis.core.proactive.policy import (
    DEFAULT_FILLERS,
    DefaultProactivityPolicy,
    ProactivityPolicy,
)
from jarvis.core.proactive.triggers import (
    ActivityClock,
    AnyTrigger,
    ExternalTrigger,
    IdleTrigger,
    IntervalTrigger,
    ReflectionTrigger,
)
from jarvis.core.proactive.types import (
    ProactiveDecision,
    ProactiveMessage,
    ResponsePlan,
)

__all__ = [
    "DEFAULT_FILLERS",
    "ActivityClock",
    "AnyTrigger",
    "DefaultProactivityCore",
    "DefaultProactivityPolicy",
    "EmitProactive",
    "ExternalTrigger",
    "FeedbackLearner",
    "IdleTrigger",
    "IntervalTrigger",
    "ReflectionTrigger",
    "ProactiveDecision",
    "ProactiveMessage",
    "ProactivityCore",
    "ProactivityDaemon",
    "ProactivityPolicy",
    "ReflectOnce",
    "ReflectTargets",
    "ResponsePlan",
    "RunMain",
]
