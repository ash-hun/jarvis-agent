"""[ui] 에이전트 REST: 이 서버에 뜬 최상위 에이전트 목록(이름, 설명, 색)을 화면에 준다."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from jarvis.app.agent_profile import AgentProfile
from jarvis.ui.web.web_state import WebState

AGENTS_EXAMPLE = {"agents": [
    {"id": "main", "name": "J.A.R.V.I.S.", "description": "", "quote": "Proof the Heart",
     "palette": {"primary": "#5fc8e2", "accent": "#f0b35f", "background": "#02060c", "nebula": []}, "main": True},
    {"id": "karen", "name": "K.A.R.E.N.", "description": "정보 수집 담당", "quote": "Eyes on everything",
     "palette": {"primary": "#f0607c", "accent": "#ffd166", "background": "#02060c", "nebula": []}, "main": False},
]}


def agent_summary(profile: AgentProfile) -> dict[str, object]:
    """화면이 에이전트를 그릴 때 필요한 것만. 모델과 프롬프트는 내보내지 않는다."""
    return {
        "id": profile.agent_id,
        "name": profile.name,
        "description": profile.description,
        "quote": profile.brand.quote,
        "palette": profile.brand.palette.model_dump(),
        "main": profile.is_main,
    }


def build_agent_router(state: WebState) -> APIRouter:
    router = APIRouter(tags=["agents"])
    agents = state.assembly.agents

    @router.get(
        "/api/agents",
        summary="최상위 에이전트 목록",
        description="main(JARVIS)이 첫 번째이고 나머지는 정의 파일 이름순. 세션 만들기의 agent 값으로 id 를 쓴다.",
        responses={200: {"content": {"application/json": {"example": AGENTS_EXAMPLE}}}},
    )
    async def list_agents() -> JSONResponse:
        return JSONResponse({"agents": [agent_summary(p) for p in agents.profiles()]})

    return router
