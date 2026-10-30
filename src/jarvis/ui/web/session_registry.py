"""[ui] SessionRegistry: Web HUD 의 세션을 id 로 만들고 찾고 지운다. 세션마다 에이전트와 보안 파이프라인을 따로 둔다."""

import time
import uuid
from typing import TYPE_CHECKING
from collections.abc import Callable

from jarvis.agent_layer.session.protocol import NOT_CONVERSATION
from jarvis.ui.web.web_auth import auth_enabled
from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.agent_layer.session.protocol import SessionMetadata, SessionRepo
    from jarvis.memory.memory_service import MemoryService
    from jarvis.core.policy.sandbox import DefaultSandbox
    from jarvis.app.agent_registry import AgentRegistry
    from jarvis.core.tools.registry import ToolRegistry
    from jarvis.model_layer.types import ModelConfig
    from jarvis.app.app_services import AppServices
    from jarvis.app.app_context import AppContext
    from jarvis.core.session import AgentSession

logger = get_logger(__name__)


# 세션을 처음 열 때 부르는 훅(세션 id, 에이전트 id, 세션). 활동 표시가 이벤트를 구독한다
SessionOpened = Callable[[str, str, "AgentSession"], None]


def last_conversation(metas: "list[SessionMetadata]", agent_id: str) -> str | None:
    """저장된 세션 중 그 에이전트와 사용자가 가장 최근에 나눈 대화. 없으면 None. 순수 함수."""
    talked = [m for m in metas if m.agent_id == agent_id and m.message_count > 0
              and not m.session_id.startswith(NOT_CONVERSATION)]
    return max(talked, key=lambda m: m.updated_at).session_id if talked else None


class UnknownAgent(ValueError):
    """정의에 없는 에이전트 id. 새 세션 요청이면 사용자 입력 오류, 옛 세션이면 정의 파일이 빠진 것이다."""


class SessionRegistry:
    """열린 세션과 그 sandbox 를 기억한다. 프로세스 메모리라 재시작하면 목록이 비고, 세션 이력은 저장소에 남는다."""

    def __init__(self, ctx: "AppContext", services: "AppServices", agents: "AgentRegistry") -> None:
        self._ctx = ctx
        self._services = services
        self._agents = agents
        self._sessions: dict[str, AgentSession] = {}
        self._session_agents: dict[str, str] = {}
        self._sandboxes: dict[str, DefaultSandbox] = {}
        self._on_open: list[SessionOpened] = []
        # 최근 사용자 활동 시각(monotonic). 외부 이벤트를 어느 세션이 소비할지 정렬용
        self._last_activity: dict[str, float] = {}

    def on_open(self, hook: SessionOpened) -> None:
        self._on_open.append(hook)

    def _session_services(self, agent_id: str, peer: bool = False) -> "tuple[AppServices, DefaultSandbox]":
        """세션 전용 sandbox 와 pipeline 을 새로 만들어 끼운 서비스 사본."""
        from jarvis.core.policy.authenticator import ApiKeyAuthenticator, NoAuthAuthenticator
        from jarvis.core.policy.pipeline import AuthenticatorProtocol, SecurityPipeline
        from jarvis.core.policy.validator import DefaultInputValidator
        from jarvis.core.policy.sandbox import DefaultSandbox
        from jarvis.core.policy.policy import AllowAllPolicy

        s = self._ctx.settings
        sandbox = DefaultSandbox(
            dangerous_patterns=s.security.dangerous_commands,
            require_approval_for=s.security.require_approval_for,
            approval_rules=self._agents.approval_rules(agent_id),
        )
        # 접근 키가 있으면 키 → (이름, roles) 로 사용자를 식별한다. AuthContext.user_id 가 이름이 되어
        # rate limit 과 tool executor 의 사용자별 정책에 그대로 흐른다
        authenticator: AuthenticatorProtocol = NoAuthAuthenticator()
        # 에이전트 대화 세션은 부른 쪽이 이미 인증했다. 사용자는 부른 쪽 범위에서 받는다(inherit_scope)
        if auth_enabled(s) and not peer:
            keys = s.security.api_keys
            authenticator = ApiKeyAuthenticator(
                valid_keys={k: frozenset(u.roles) for k, u in keys.items()},
                user_names={k: u.name for k, u in keys.items()},
            )
        pipeline = SecurityPipeline(
            validator=DefaultInputValidator(max_length=s.security.input_max_length),
            authenticator=authenticator,
            policy=AllowAllPolicy(),
            sandbox=sandbox,
        )
        return self._services.with_security(pipeline, sandbox), sandbox

    async def get_or_create(
        self, session_id: str, agent_id: str | None = None, peer: bool = False
    ) -> "tuple[AgentSession, DefaultSandbox]":
        """있으면 그대로, 없으면 저장소에 만들고 조립한다. 두 번 불러도 같은 세션이다.

        에이전트는 세션을 처음 만들 때만 정한다. 저장소에 이미 있는 세션은 저장된 에이전트로 열고 agent_id 는 무시한다.
        peer 는 다른 에이전트가 부른 대화 세션이다. 처음 열 때만 의미가 있다.
        """
        if session_id not in self._sessions:
            agent = await self._resolve_agent(session_id, agent_id)
            await self._ctx.session_repo.create(session_id=session_id, agent_id=agent)
            services, sandbox = self._session_services(agent, peer)
            session = self._agents.builder(agent).build(session_id, services, inherit_scope=peer)
            self._sessions[session_id] = session
            self._sandboxes[session_id] = sandbox
            self._session_agents[session_id] = agent
            for hook in self._on_open:
                hook(session_id, agent, session)
        return self._sessions[session_id], self._sandboxes[session_id]

    async def _resolve_agent(self, session_id: str, agent_id: str | None) -> str:
        meta = await self._ctx.session_repo.get_meta(session_id)
        agent = meta.agent_id if meta is not None else (agent_id or self._agents.main.agent_id)
        if agent not in self._agents:
            raise UnknownAgent(agent)
        return agent

    async def create_new(self, agent_id: str | None = None) -> str:
        sid = uuid.uuid4().hex[:8]
        await self.get_or_create(sid, agent_id)
        return sid

    async def remove(self, session_id: str) -> None:
        """메모리와 저장소에서 지운다. 없는 세션도 같은 결과(저장소 delete 는 no-op)."""
        self._sessions.pop(session_id, None)
        self._sandboxes.pop(session_id, None)
        self._session_agents.pop(session_id, None)
        self._last_activity.pop(session_id, None)
        await self._ctx.session_repo.delete(session_id)

    def agent_of(self, session_id: str) -> str:
        """열린 세션의 에이전트 id. 열리지 않은 세션은 main."""
        return self._session_agents.get(session_id, self._agents.main.agent_id)

    def tool_registry_of(self, session_id: str) -> "ToolRegistry | None":
        """열린 세션이 쓰는 도구 레지스트리(에이전트 정의의 부분집합일 수 있다). 열리지 않았으면 None."""
        session = self._sessions.get(session_id)
        return session._tool_registry if session is not None else None

    def session_agents(self) -> dict[str, str]:
        """열린 세션 id → 에이전트 id. 목록 순서는 list_ids 와 같다."""
        return {sid: self._session_agents[sid] for sid in self._sessions}

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def active_sessions(self) -> "list[AgentSession]":
        return list(self._sessions.values())

    def touch(self, session_id: str) -> None:
        """사용자 메시지를 받은 시점. 세션 recency 를 갱신한다."""
        self._last_activity[session_id] = time.monotonic()

    def latest_of(self, agent_id: str) -> "AgentSession | None":
        """사용자가 그 에이전트와 가장 최근에 대화한 세션. 사용자가 말한 적 없는 세션(위임 등)은 빼고, 없으면 None."""
        talked = [sid for sid in self._last_activity if self._session_agents.get(sid) == agent_id]
        if not talked:
            return None
        return self._sessions[max(talked, key=lambda sid: self._last_activity[sid])]

    async def conversation_of(self, agent_id: str) -> "AgentSession":
        """그 에이전트에게 먼저 말을 건넬 세션. 지금 열린 대화가 없으면(재시작 뒤) 저장된 마지막 대화를 다시 열고,
        그것도 없으면 새 대화를 만든다. 대화 기록에 남아야 사용자가 이어 묻는다."""
        session = self.latest_of(agent_id)
        if session is not None:
            return session
        saved = last_conversation(await self._ctx.session_repo.list(""), agent_id)
        session_id = saved or await self.create_new(agent_id)
        session, _ = await self.get_or_create(session_id, agent_id)
        self.touch(session_id)
        return session

    def sessions_by_recency(self) -> "list[AgentSession]":
        """최근 활동순. 한 번도 touch 되지 않았으면 삽입 순서.

        외부 이벤트는 inbox drain-once 라 첫 세션이 전부 소비한다. 그 첫 세션을 가장 최근에 대화한 세션으로 만든다.
        """
        items = list(self._sessions.items())
        items.sort(key=lambda kv: self._last_activity.get(kv[0], float("-inf")), reverse=True)
        return [session for _, session in items]

    async def save_all_sessions(
        self, session_repo: "SessionRepo", memory: "MemoryService", model: "ModelConfig"
    ) -> None:
        """서버 종료 때 활성 세션마다 일화 요약, 사실 공고화, 절차 학습. 한 세션의 실패가 다른 세션을 막지 않는다."""
        from jarvis.memory.consolidation.episodic import EpisodicSummarizer
        from jarvis.app.session_builder import learn_procedures

        summarizer = EpisodicSummarizer(model=model, memory=memory)
        for session_id, session in list(self._sessions.items()):
            try:
                # 응답과 함께 띄운 사고와 AGENDA 판단을 끊지 않고 마무리한다
                await session.settle()
                msgs = await session_repo.get_messages(session._session_id)
                if not msgs:
                    continue
                scope = session.memory_scope
                entry_id = await summarizer.save_session(session._session_id, msgs, scope=scope)
                if entry_id:
                    logger.info(f"[Episodic] Session {session_id[:8]} summary saved (id: {entry_id[:8]})")
                facts = await memory.consolidate(scope)
                if facts:
                    logger.info(f"[Memory] Session {session_id[:8]}: {facts} fact(s) consolidated")
                learned = await learn_procedures(self._ctx, session._session_id, msgs)
                if learned:
                    logger.info(f"[Procedures] Session {session_id[:8]}: draft(s) saved: {', '.join(learned)}")
            except Exception as exc:
                logger.info(f"[Episodic] Session {session_id[:8]} summary failed (non-fatal): {exc}")
