"""[ui] WebState: Web HUD 라우터들이 같이 보는 실행 상태(조립 결과, 세션, 승인 브로커, 열린 연결, 놓친 알림)."""

import time
from pathlib import Path
from collections import deque
from typing import TYPE_CHECKING
from collections.abc import Callable

from jarvis.core.notify.dedupe import SPOKEN_DEDUPE_SEC, RecentOnce
from jarvis.voice.phrases import load_phrase_texts, load_phrases
from jarvis.voice.english import Translate, make_llm_translator
from jarvis.ui.web.session_registry import SessionRegistry
from jarvis.ui.web.agent_activity import AgentActivity
from jarvis.ui.web.approvals import SessionApprovals
from jarvis.common.logger import get_logger

if TYPE_CHECKING:
    from jarvis.core.focus.focus_service import FocusService, SubAgent
    from jarvis.agent_layer.thought.reply import ReplyClassifier
    from jarvis.ui.web.adapter import PerConnectionAdapter
    from jarvis.voice.voice_service import VoiceService
    from jarvis.app.app_assembly import AppAssembly
    from jarvis.jarvis_config import JarvisSettings
    from jarvis.app.app_context import AppContext
    from jarvis.core.session import AgentSession
    from jarvis.voice.wake import WakeDetector

logger = get_logger(__name__)

# 열린 HUD 가 없을 때 쌓아 두는 스케줄 알림 수. 프로세스 메모리라 재시작하면 사라진다
PENDING_NOTICE_MAX = 20


async def _focus_outside_ws(_args: str) -> str:
    return "[Focus] Web HUD 에서만 쓸 수 있습니다."


class WebState:
    """create_app 이 하나 만들어 모든 라우터에 넘긴다. 연결과 알림 큐는 프로세스 메모리에만 있다."""

    def __init__(self, assembly: "AppAssembly") -> None:
        self.assembly = assembly
        self.registry = SessionRegistry(assembly.ctx, assembly.services, assembly.agents)
        # 세션별 승인 브로커. 같은 세션의 모든 연결이 모달을 받고 먼저 온 답을 쓴다
        self.approvals: dict[str, SessionApprovals] = {}
        self.live_clients: set[PerConnectionAdapter] = set()
        self.pending_notices: deque[dict[str, object]] = deque(maxlen=PENDING_NOTICE_MAX)
        self.voice_service = self._build_voice_service()
        # JARVIS 의 한국어 답을 소리로만 영어로 옮긴다. 영어 TTS 가 없으면 옮겨도 JARVIS 목소리가 아니라 끈다
        self.translate_english: Translate | None = None
        if self.settings.voice.speak_english and self.voice_service is not None and self.voice_service.has_english_tts:
            self.translate_english = make_llm_translator(assembly.services.model_config)
        # 미리 녹음한 읽기 문구. 이름은 connected 로 화면에 알리고 wav 는 /api/voice/phrases 가 내준다
        self.phrases: dict[str, Path] = load_phrases(self.settings.voice.phrases_dir)
        # 화면이 녹음 문구를 재생하면 그 문장을 밖(디스코드 등)에 알린다
        self.phrase_texts: dict[str, str] = load_phrase_texts(self.settings.voice.phrases_dir)
        # 같은 세션을 연 화면들이 읽었다고 알려 온 같은 말은 한 번만 밖에 보낸다. 재시작하면 잊는다
        self.spoken_once = RecentOnce(SPOKEN_DEDUPE_SEC, time.monotonic)
        # 연결마다 웨이크워드 감지기를 하나씩 만든다. 꺼져 있거나 준비가 안 되면 None
        self.wake: Callable[[], WakeDetector] | None = self._build_wake_factory()
        self.focus: FocusService | None = self._build_focus_service()
        if self.focus is not None and assembly.ctx.dispatcher is not None:
            # 실행은 ws 가 디스패처보다 먼저 가로챈다. 여기 등록은 입력창의 명령 목록에 보이게 하려는 것
            assembly.ctx.dispatcher.register("focus", _focus_outside_ws, "<작업> Focus 모드 시작 | stop 종료 | 현황")
        # 🔔 짧은 답과 음성 승인 답 분류기. 사고가 꺼져 있으면 None 이고 화면은 키워드만 쓴다
        self.reply_classifier: ReplyClassifier | None = assembly.profile.reply_classifier()
        # 어느 에이전트가 일하는지. 둘 이상이면 HUD 구체가 색을 섞는다
        self.activity = AgentActivity(self.broadcast_live)
        self.registry.on_open(self.activity.watch)
        # 에이전트끼리 묻는 도구가 받는 쪽 세션을 이 화면의 세션 목록에 열게 한다
        from jarvis.app.agent_conversation import ASK_AGENT_TOOL, AskAgentTool

        ask_tool = assembly.ctx.tool_registry.get(ASK_AGENT_TOOL)
        if isinstance(ask_tool, AskAgentTool):
            ask_tool.set_opener(self.open_peer_session)

    @property
    def ctx(self) -> "AppContext":
        return self.assembly.ctx

    @property
    def settings(self) -> "JarvisSettings":
        return self.assembly.ctx.settings

    def _build_focus_service(self) -> "FocusService | None":
        """Focus 모드 서비스. 시각과 작업 id 는 여기(경계)에서 만들어 넣는다."""
        cfg = self.settings.focus
        if not cfg.enabled:
            return None
        import uuid
        from datetime import datetime

        from jarvis.core.focus.prompts import REFERENCE_TOOLS, SYSTEM_PROMPTS
        from jarvis.core.multi_agent.factory import AgentDefinition
        from jarvis.core.focus.focus_service import FocusService
        from jarvis.app.subagent_builder import SubagentBuilder
        from jarvis.core.focus.focus_store import FocusStore

        ctx, services = self.assembly.ctx, self.assembly.services
        builder = SubagentBuilder(ctx, services, ctx.tool_registry)

        async def make_agent(role: str, session_id: str) -> "SubAgent":
            definition = AgentDefinition(
                name=f"focus-{role}",
                description=f"Focus 모드 {role} 담당",
                system_prompt=SYSTEM_PROMPTS[role],
                tools=REFERENCE_TOOLS if role == "reference" else [],
                tools_only=True,
                model_override=cfg.model or None,
            )
            await ctx.session_repo.create(session_id=session_id)
            return builder.build_session(definition, session_id)

        return FocusService(
            store=FocusStore(cfg.dir),
            make_agent=make_agent,
            clock=time.time,
            new_id=lambda: f"{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6]}",
            ready_timeout_sec=cfg.ready_timeout_sec,
        )

    def _build_voice_service(self) -> "VoiceService | None":
        """음성 프로바이더를 설정대로 만든다. 선택 의존성이 없으면 None(브라우저 음성만)."""
        try:
            from jarvis.voice.voice_service import VoiceService

            v = self.settings.voice
            return VoiceService.from_config(
                stt_provider=v.stt_provider,
                tts_provider=v.tts_provider,
                stt_options=v.stt_options(),
                tts_options=v.tts_options(),
                english_tts_provider=v.english_tts_provider,
                english_tts_options=v.english_tts_options(),
            )
        except Exception as exc:
            logger.warning(f"[Voice] 서버 음성 비활성화, 브라우저 음성만 쓴다 (초기화 실패): {exc}")
            return None

    def _build_wake_factory(self) -> "Callable[[], WakeDetector] | None":
        """설정과 모델 파일, 선택 의존성을 기동 때 한 번 확인한다. 하나라도 없으면 웨이크워드를 끈다."""
        v = self.settings.voice
        if not v.wake_model_dir:
            return None
        from jarvis.voice.wake import WakeDetector, missing_wake_files, openwakeword_scorer

        missing = missing_wake_files(v.wake_model_dir)
        try:
            import openwakeword  # noqa: F401
        except ImportError:
            missing.append("openwakeword(uv sync --extra wake)")
        if missing:
            logger.warning(f"[Voice] 웨이크워드 비활성화, 없는 것: {', '.join(missing)}")
            return None
        return lambda: WakeDetector(openwakeword_scorer(v.wake_model_dir), v.wake_threshold)

    def broker(self, session_id: str) -> SessionApprovals:
        """세션의 승인 브로커. 없으면 만든다."""
        return self.approvals.setdefault(session_id, SessionApprovals())

    async def open_peer_session(
        self, agent_id: str, session_id: str, caller_session_id: str | None
    ) -> "AgentSession":
        """다른 에이전트가 부른 대화 세션. 받는 쪽 도구의 승인 요청은 부른 세션의 화면으로 보낸다."""
        session, sandbox = await self.registry.get_or_create(session_id, agent_id, peer=True)
        if caller_session_id is not None:
            sandbox.set_approval_callback(self.broker(caller_session_id).request)
        return session

    async def converse(self, agent_id: str, text: str) -> bool:
        """스케줄 결과를 그 에이전트와 최근 대화한 세션에 에이전트의 말로 건넨다. 건넸으면 True.

        열린 대화가 없어도(재시작 뒤, 한동안 말이 없을 때) 저장된 마지막 대화에 건넨다.
        알림 제목 대신 에이전트의 말로 온다.
        """
        session = await self.registry.conversation_of(agent_id)
        return await session.say(text)

    async def broadcast_live(self, payload: dict[str, object]) -> None:
        """열린 HUD 에만 보낸다. 지금 상태를 알리는 것이라 아무도 없으면 버린다."""
        for adapter in list(self.live_clients):
            await adapter.send(payload)

    async def broadcast_notice(self, payload: dict[str, object]) -> None:
        """스케줄 실행 결과를 열린 HUD 전부에 보낸다. 열린 HUD 가 없으면 다음 접속 때 missed 로 보낸다."""
        if not self.live_clients:
            self.pending_notices.append(payload)
            return
        for adapter in list(self.live_clients):
            await adapter.send(payload)
