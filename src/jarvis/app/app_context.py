"""[app] AppContext: 화면(TUI, Web)이 기동 뒤 붙잡고 쓰는 앱 단위 인프라 묶음."""

from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.core.proactive.triggers import ActivityClock, ReflectionTrigger
    from jarvis.core.external import ExternalEventInbox, ExternalEventPoller
    from jarvis.core.slash.dispatcher import SlashCommandDispatcher
    from jarvis.agent_layer.session.protocol import SessionRepo
    from jarvis.core.procedures.learner import ProcedureLearner
    from jarvis.core.proactive.feedback import FeedbackLearner
    from jarvis.core.scheduler.service import SchedulerService
    from jarvis.memory.memory_service import MemoryService
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.core.session import AgentSession
    from jarvis.config import JarvisSettings
    from jarvis.core.notify import Notify


@dataclass
class AppContext:
    """기동 때 한 번 만들고 화면이 끝날 때까지 들고 있는 인프라. 세션마다 달라지는 것은 담지 않는다."""

    session_repo: "SessionRepo"
    tool_registry: "ToolRegistry"
    settings: "JarvisSettings"
    # Ctrl+N 새 세션, Ctrl+F 분기 팩토리. TUI 진입점이 주입한다
    session_factory: "Callable[[], Awaitable[AgentSession]] | None" = field(default=None)
    branch_factory: "Callable[[str], Awaitable[AgentSession]] | None" = field(default=None)
    scheduler: "SchedulerService | None" = field(default=None)
    dispatcher: "SlashCommandDispatcher | None" = field(default=None)
    # 활동 시계, 성찰 트리거, 피드백 학습기: 앱에 하나
    activity_clock: "ActivityClock | None" = field(default=None)
    reflection_trigger: "ReflectionTrigger | None" = field(default=None)
    feedback_learner: "FeedbackLearner | None" = field(default=None)
    # 외부 이벤트 소스가 없으면 둘 다 None
    external_inbox: "ExternalEventInbox | None" = field(default=None)
    external_poller: "ExternalEventPoller | None" = field(default=None)
    # idle 공고화와 종료 요약이 쓴다
    memory: "MemoryService | None" = field(default=None)
    # 스케줄 결과와 proactive 발화를 받는 외부 채널(슬랙 등). 설정이 없으면 None
    notifier: "Notify | None" = field(default=None)
    # 세션 종료 때 다단계 작업을 절차 초안으로 남긴다. 꺼져 있으면 None
    procedure_learner: "ProcedureLearner | None" = field(default=None)
    # 정의의 tools 에 이름을 적은 에이전트만 쓰는 도구(청약 공고 조회 등). 앱 레지스트리에 없어 JARVIS 에게는 안 보인다
    agent_tools: "ToolRegistry | None" = field(default=None)
