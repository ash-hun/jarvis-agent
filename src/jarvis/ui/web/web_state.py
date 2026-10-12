"""[ui] WebState: Web HUD 라우터들이 같이 보는 실행 상태(조립 결과, 세션, 승인 브로커, 열린 연결, 놓친 알림)."""

from collections import deque
from typing import TYPE_CHECKING

from jarvis.common.logger import get_logger
from jarvis.ui.web.approvals import SessionApprovals
from jarvis.ui.web.session_registry import SessionRegistry

if TYPE_CHECKING:
    from jarvis.agent_layer.thought.reply import ReplyClassifier
    from jarvis.app.app_assembly import AppAssembly
    from jarvis.app.app_context import AppContext
    from jarvis.config import JarvisSettings
    from jarvis.ui.web.adapter import PerConnectionAdapter
    from jarvis.voice.service import VoiceService

logger = get_logger(__name__)

# 열린 HUD 가 없을 때 쌓아 두는 스케줄 알림 수. 프로세스 메모리라 재시작하면 사라진다
PENDING_NOTICE_MAX = 20


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
        # 🔔 짧은 답과 음성 승인 답 분류기. 사고가 꺼져 있으면 None 이고 화면은 키워드만 쓴다
        self.reply_classifier: ReplyClassifier | None = assembly.profile.reply_classifier()

    @property
    def ctx(self) -> "AppContext":
        return self.assembly.ctx

    @property
    def settings(self) -> "JarvisSettings":
        return self.assembly.ctx.settings

    def _build_voice_service(self) -> "VoiceService | None":
        """음성 프로바이더를 설정대로 만든다. 선택 의존성이 없으면 None(브라우저 음성만)."""
        try:
            from jarvis.voice.service import VoiceService

            v = self.settings.voice
            return VoiceService.from_config(stt_provider=v.stt_provider, tts_provider=v.tts_provider)
        except Exception:
            return None

    def broker(self, session_id: str) -> SessionApprovals:
        """세션의 승인 브로커. 없으면 만든다."""
        return self.approvals.setdefault(session_id, SessionApprovals())

    async def broadcast_notice(self, payload: dict[str, object]) -> None:
        """스케줄 실행 결과를 열린 HUD 전부에 보낸다. 열린 HUD 가 없으면 다음 접속 때 missed 로 보낸다."""
        if not self.live_clients:
            self.pending_notices.append(payload)
            return
        for adapter in list(self.live_clients):
            await adapter.send(payload)
