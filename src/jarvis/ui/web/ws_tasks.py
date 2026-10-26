"""[ui] ws 메시지 하나가 띄우는 비동기 작업(프롬프트, STT, TTS, 짧은 답 분류)과 피드백 중복 판정."""

import base64
import contextlib
from fastapi import WebSocket
from typing import TYPE_CHECKING, Any

from jarvis.app.agent_profile import MAIN_AGENT_ID
from jarvis.common.logger import get_logger
from jarvis.voice.service import is_unclear

if TYPE_CHECKING:
    from jarvis.agent_layer.thought.reply import ReplyClassifier
    from jarvis.ui.web.adapter import PerConnectionAdapter
    from jarvis.core.focus.service import FocusService
    from jarvis.core.focus.types import FocusCommand
    from jarvis.voice.service import VoiceService
    from jarvis.core.session import AgentSession
    from jarvis.core.notify import Notify

# 잘 못 들었을 때 되묻는 말. JARVIS 는 영어라 직전 "Yes, sir?" 와 같은 목소리(영어 TTS)로 나온다
UNCLEAR_REPLY_MAIN = "I'm sorry, sir. I didn't catch that."
UNCLEAR_REPLY = "잘 못 들었어요. 한 번 더 말씀해 주세요."

logger = get_logger(__name__)


async def notify_quietly(notify: "Notify | None", payload: dict[str, Any] | None) -> None:
    """밖으로 알린다. 알림 채널이 실패해도 읽기와 대화는 계속된다."""
    if notify is None or payload is None:
        return
    with contextlib.suppress(Exception):
        await notify(payload)


async def run_prompt(
    session: "AgentSession", adapter: "PerConnectionAdapter", text: str, credentials: dict[str, str]
) -> None:
    try:
        await session.prompt(text, credentials=credentials)
    except Exception as exc:
        await adapter.show_error(str(exc))


async def run_focus(
    session: "AgentSession",
    adapter: "PerConnectionAdapter",
    focus: "FocusService",
    command: "FocusCommand",
    credentials: dict[str, str],
) -> None:
    """/focus 명령을 처리해 안내를 한 메시지로 보이고, 시작이면 작업을 메인 에이전트에 이어 보낸다."""
    try:
        feedback, follow_up = await focus.handle(command, session)
    except Exception as exc:
        await adapter.show_error(f"Focus 오류: {exc}")
        return
    await adapter.send({"type": "agent_start"})
    await adapter.send({"type": "stream_delta", "text": feedback})
    # 이어서 메인 에이전트가 돌면 화면이 음성 요청 표시와 입력 잠금을 그대로 두게 알린다
    await adapter.send({"type": "agent_end", "continues": bool(follow_up)})
    if follow_up:
        await run_prompt(session, adapter, follow_up, credentials)


def unclear_reply(agent_id: str) -> str:
    return UNCLEAR_REPLY_MAIN if agent_id == MAIN_AGENT_ID else UNCLEAR_REPLY


async def run_stt(
    ws: WebSocket, voice_service: "VoiceService", audio_b64: str, sample_rate: int, agent_id: str = MAIN_AGENT_ID
) -> None:
    """base64 오디오를 전사해 결과를 보낸다. 잘 못 들었으면 에이전트에 넘기지 않고 되묻는 말을 읽어 준다."""
    try:
        audio_bytes = base64.b64decode(audio_b64)
        heard = await voice_service.transcribe_scored(audio_bytes, sample_rate)
    except Exception as exc:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "voice_stt_result", "text": "", "error": str(exc)})
        return
    # 기준값을 실제 기록으로 맞추려고 남긴다
    logger.info(
        f"[Voice] stt no_speech={heard.no_speech_prob:.2f} logprob={heard.avg_logprob:.2f} text={heard.text!r}"
    )
    if not is_unclear(heard):
        await ws.send_json({"type": "voice_stt_result", "text": heard.text})
        return
    await ws.send_json({"type": "voice_stt_result", "text": "", "unclear": True, "heard": heard.text})
    await run_tts(ws, voice_service, unclear_reply(agent_id), "ko")


async def run_tts(
    ws: WebSocket, voice_service: "VoiceService", text: str, lang: str, request_id: object = None
) -> None:
    """서버 TTS 결과를 보낸다. 브라우저 TTS 프로바이더면 빈 data 와 원문을 돌려 화면이 직접 읽게 한다."""
    try:
        audio_bytes = await voice_service.synthesize(text, lang)
        if audio_bytes:
            await ws.send_json({
                "type": "voice_tts_audio",
                "data": base64.b64encode(audio_bytes).decode(),
                "mime": "audio/wav",
                "id": request_id,
            })
        else:
            await ws.send_json({"type": "voice_tts_audio", "data": "", "text": text, "id": request_id})
    except Exception as exc:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": f"TTS 오류: {exc}"})


def first_feedback(seen: set[str], message_id: object) -> bool:
    """이 연결에서 처음 받는 🔔 피드백이면 True. id 가 없으면(옛 화면) 매번 True."""
    if not isinstance(message_id, str) or not message_id:
        return True
    if message_id in seen:
        return False
    seen.add(message_id)
    return True


async def run_reply_classify(
    ws: WebSocket,
    classifier: "ReplyClassifier | None",
    session: "AgentSession",
    feedback_ids: set[str],
    msg: dict[str, object],
) -> None:
    """짧은 답을 분류해 돌려준다. 🔔 피드백이면 여기서 학습까지 하고, 승인은 화면이 답을 보낸다."""
    from jarvis.agent_layer.thought.reply import FALLBACK

    kind = msg.get("kind")
    if kind != "feedback" and kind != "approval":
        return
    text = str(msg.get("text", ""))
    context = str(msg.get("context", ""))
    has_always = bool(msg.get("has_always", False))
    if classifier is None:
        verdict = FALLBACK[kind]
    else:
        verdict = await classifier.classify(kind, text, context, has_always)
    if kind == "feedback" and verdict in ("accept", "dismiss") and first_feedback(feedback_ids, msg.get("id")):
        await session.record_feedback(verdict == "accept")
    with contextlib.suppress(Exception):
        await ws.send_json({"type": "reply_classified", "kind": kind, "id": msg.get("id"), "verdict": verdict})
