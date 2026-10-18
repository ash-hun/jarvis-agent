"""[app] AppServices: 세션을 만들 때 넘기는 앱 단위 서비스 묶음(예전 extra dict)."""

from typing import TYPE_CHECKING
from dataclasses import dataclass, replace

if TYPE_CHECKING:
    from jarvis.agent_layer.usermodel.store import UserModelStore
    from jarvis.agent_layer.openloop.store import OpenLoopStore
    from jarvis.core.policy.approval_rules import ApprovalRules
    from jarvis.core.procedures.learner import ProcedureLearner
    from jarvis.core.external.inbox import ExternalEventInbox
    from jarvis.core.policy.pipeline import SecurityPipeline
    from jarvis.core.proactive.triggers import ActivityClock
    from jarvis.memory.memory_service import MemoryService
    from jarvis.core.policy.sandbox import DefaultSandbox
    from jarvis.core.skills.registry import SkillRegistry
    from jarvis.core.plugins.runner import PluginRunner
    from jarvis.model_layer.types import ModelConfig


@dataclass(frozen=True)
class AppServices:
    """기동 때 한 번 만드는 서비스들. 세션마다 다른 것은 보안 파이프라인과 sandbox 뿐이라 with_security 로 바꿔 낀다."""

    pipeline: "SecurityPipeline"
    plugin_runner: "PluginRunner"
    skill_registry: "SkillRegistry"
    sandbox: "DefaultSandbox"
    approval_rules: "ApprovalRules"
    memory: "MemoryService"
    model_config: "ModelConfig"
    activity_clock: "ActivityClock"
    procedure_learner: "ProcedureLearner | None" = None
    openloop_store: "OpenLoopStore | None" = None
    user_model_store: "UserModelStore | None" = None
    external_inbox: "ExternalEventInbox | None" = None

    def with_security(self, pipeline: "SecurityPipeline", sandbox: "DefaultSandbox") -> "AppServices":
        """같은 서비스에 세션 전용 파이프라인과 sandbox 만 바꾼 사본. 원본은 그대로 둔다."""
        return replace(self, pipeline=pipeline, sandbox=sandbox)
