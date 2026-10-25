"""[app] 최상위 에이전트 정의 파일을 읽어 에이전트마다 AgentProfile 과 SessionBuilder 를 들고 있는 레지스트리."""

import re
import yaml
from pathlib import Path
from typing import TYPE_CHECKING
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.app.agent_profile import MAIN_AGENT_ID, AgentProfile, compose_system_prompt
from jarvis.app.session_builder import SessionBuilder
from jarvis.config import BrandConfig, BrandPalette
from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.core.policy.approval_rules import ApprovalRules
    from jarvis.core.scheduler.service import TaskAgent
    from jarvis.app.app_services import AppServices
    from jarvis.app.app_context import AppContext
    from jarvis.core.session import AgentSession

# 파일 이름이 곧 id 다. 세션, 기억, 약속, 승인 파일 이름에 그대로 들어가므로 좁게 받는다
AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SPEC_SUFFIX = ".yaml"

logger = get_logger(__name__)


class AgentSpec(BaseModel):
    """정의 파일 한 장. 비운 항목은 main 의 설정을 이어받는다."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    quote: str = ""
    palette: BrandPalette = Field(default_factory=BrandPalette)
    # 말투와 성격. 비우면 개성 없이 업무 지시(system_prompt)만 쓴다. main 의 개성은 이어받지 않는다
    persona: str = ""
    system_prompt: str | None = None
    # 모델 이름만 바꾼다. 프로바이더, 키, 주소는 main 것을 쓴다
    model: str | None = None
    # 비우면 도구 전체
    tools: list[str] = Field(default_factory=list)
    # 비우면 main 의 proactive 설정 그대로
    proactive: bool | None = None


def load_agent_specs(team_dir: str) -> dict[str, AgentSpec]:
    """디렉터리의 *.yaml 을 이름순으로 읽는다. 잘못된 파일은 로그만 남기고 건너뛴다(다른 에이전트는 뜬다)."""
    root = Path(team_dir).expanduser()
    if not root.is_dir():
        return {}
    specs: dict[str, AgentSpec] = {}
    for path in sorted(root.glob(f"*{SPEC_SUFFIX}")):
        agent_id = path.stem
        # main 은 env 설정이 정본이다. 파일로 덮으면 정본이 둘이 된다
        if agent_id == MAIN_AGENT_ID or not AGENT_ID_PATTERN.match(agent_id):
            logger.info(f"[Team] skip '{path.name}': id must match {AGENT_ID_PATTERN.pattern} and not be 'main'")
            continue
        try:
            specs[agent_id] = AgentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except (yaml.YAMLError, ValidationError) as exc:
            logger.info(f"[Team] skip '{path.name}': {exc}")
    return specs


def profile_from_spec(agent_id: str, spec: AgentSpec, main: AgentProfile) -> AgentProfile:
    """정의 한 장을 main 위에 얹어 AgentProfile 로. 피드백 학습기는 에이전트마다 새로 만든다."""
    from jarvis.core.proactive import FeedbackLearner

    model = main.model.model_copy(update={"model": spec.model}) if spec.model else main.model
    proactive = main.proactive if spec.proactive is None else main.proactive.model_copy(
        update={"enabled": spec.proactive}
    )
    return AgentProfile(
        agent_id=agent_id,
        brand=BrandConfig(name=spec.name, quote=spec.quote, palette=spec.palette, persona=spec.persona),
        model=model,
        thought=main.thought,
        proactive=proactive,
        feedback_learner=FeedbackLearner(base_threshold=proactive.effective_threshold()),
        description=spec.description,
        system_prompt=compose_system_prompt(spec.persona, spec.system_prompt),
        tools=tuple(spec.tools),
    )


class AgentRegistry:
    """에이전트 id → (AgentProfile, SessionBuilder). main 이 항상 첫 번째다."""

    def __init__(self, ctx: "AppContext", services: "AppServices", profiles: list[AgentProfile]) -> None:
        if not profiles or not profiles[0].is_main:
            raise ValueError("첫 프로필은 main 이어야 한다")
        self._ctx = ctx
        self._services = services
        self._builders = {p.agent_id: SessionBuilder(ctx, services, p) for p in profiles}
        # 규칙 파일 하나에 객체 하나. 세션이 여럿이어도 같은 객체를 써야 "항상 허용"이 바로 다른 세션에 보인다
        self._approval_rules: dict[str, ApprovalRules] = {}
        # 화면 없이 연 에이전트 대화 세션(TUI, 스케줄). Web 은 세션 목록에서 연다
        self._peer_sessions: dict[str, AgentSession] = {}

    @classmethod
    def load(
        cls, ctx: "AppContext", services: "AppServices", main: AgentProfile, team_dir: str
    ) -> "AgentRegistry":
        specs = load_agent_specs(team_dir)
        profiles = [main] + [profile_from_spec(agent_id, spec, main) for agent_id, spec in specs.items()]
        if specs:
            logger.info(f"[Team] {len(specs)} agent(s) loaded: {', '.join(specs)}")
        return cls(ctx, services, profiles)

    def __contains__(self, agent_id: object) -> bool:
        return agent_id in self._builders

    @property
    def main(self) -> AgentProfile:
        return self._builders[MAIN_AGENT_ID].profile

    def ids(self) -> list[str]:
        return list(self._builders)

    def profiles(self) -> list[AgentProfile]:
        return [b.profile for b in self._builders.values()]

    def get(self, agent_id: str) -> AgentProfile | None:
        builder = self._builders.get(agent_id)
        return builder.profile if builder is not None else None

    def approval_rules(self, agent_id: str) -> "ApprovalRules":
        """공용 규칙 + 이 에이전트의 규칙 파일(agent_approvals_dir/<id>.yaml). 같은 id 면 같은 객체."""
        if agent_id not in self._approval_rules:
            from jarvis.core.policy.approval_rules import ApprovalRules, LayeredApprovalRules

            path = Path(self._ctx.settings.security.agent_approvals_dir).expanduser() / f"{agent_id}{SPEC_SUFFIX}"
            self._approval_rules[agent_id] = LayeredApprovalRules(
                self._services.approval_rules, ApprovalRules(str(path))
            )
        return self._approval_rules[agent_id]

    async def open_peer_session(
        self, agent_id: str, session_id: str, caller_session_id: str | None = None
    ) -> "AgentSession":
        """다른 에이전트가 부른 대화 세션. 저장소에 없으면 만들고, 같은 id 는 같은 세션이다. 사용자는 부른 쪽 범위."""
        if session_id not in self._peer_sessions:
            await self._ctx.session_repo.create(session_id=session_id, agent_id=agent_id)
            self._peer_sessions[session_id] = self.builder(agent_id).build(session_id, inherit_scope=True)
        return self._peer_sessions[session_id]

    def task_agent(self, agent_id: str) -> "TaskAgent | None":
        """스케줄 작업을 이 에이전트로 돌릴 때 쓰는 모델, 프롬프트, 이름, 도구. 모르는 id 면 None."""
        from jarvis.core.scheduler.service import TaskAgent

        builder = self._builders.get(agent_id)
        if builder is None:
            return None
        profile = builder.profile
        return TaskAgent(
            model=profile.model, system_prompt=profile.system_prompt, agent_name=profile.agent_id,
            tools=builder.tool_registry(),
        )

    def builder(self, agent_id: str) -> SessionBuilder:
        """모르는 id 는 KeyError. 부르는 쪽이 사용자 입력을 먼저 `in` 으로 거른다."""
        return self._builders[agent_id]
