"""[app] AppAssembly: 기동 한 번의 조립 결과(인프라, 서비스, 에이전트, 세션 빌더)를 묶어 화면에 넘긴다."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.app.agent_profile import AgentProfile
    from jarvis.app.app_context import AppContext
    from jarvis.app.app_services import AppServices
    from jarvis.app.session_builder import SessionBuilder


@dataclass(frozen=True)
class AppAssembly:
    """화면이 기동 뒤에 쓰는 네 가지. 에이전트가 늘면 profile 과 sessions 가 에이전트별 묶음이 된다."""

    ctx: "AppContext"
    services: "AppServices"
    profile: "AgentProfile"
    sessions: "SessionBuilder"
