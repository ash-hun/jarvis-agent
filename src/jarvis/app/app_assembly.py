"""[app] AppAssembly: 기동 한 번의 조립 결과(인프라, 서비스, 에이전트, 세션 빌더)를 묶어 화면에 넘긴다."""

from typing import TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from jarvis.app.session_builder import SessionBuilder
    from jarvis.app.agent_registry import AgentRegistry
    from jarvis.app.agent_profile import AgentProfile
    from jarvis.app.app_services import AppServices
    from jarvis.app.app_context import AppContext


@dataclass(frozen=True)
class AppAssembly:
    """화면이 기동 뒤에 쓰는 것들. profile 과 sessions 는 main(JARVIS) 몫이고, 에이전트 전체는 agents 에 있다."""

    ctx: "AppContext"
    services: "AppServices"
    profile: "AgentProfile"
    sessions: "SessionBuilder"
    agents: "AgentRegistry"
