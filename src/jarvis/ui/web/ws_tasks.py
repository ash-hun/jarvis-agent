"""[ui] ws 메시지 하나가 띄우는 비동기 작업(프롬프트, STT, TTS, 짧은 답 분류)과 피드백 중복 판정."""

import base64
import contextlib
from typing import TYPE_CHECKING

from fastapi import WebSocket

if TYPE_CHECKING:
    from jarvis.agent_layer.thought.reply import ReplyClassifier
    from jarvis.core.session import AgentSession
    from jarvis.ui.web.adapter import PerConnectionAdapter
    from jarvis.voice.service import VoiceService


async def run_prompt(
    session: "AgentSession", adapter: "PerConnectionAdapter", text: str, credentials: dict[str, str]
) -> None:
    try:
        await session.prompt(text, credentials=credentials)
    except Exception as exc:
        await adapter.show_error(str(exc))


async def run_stt(ws: WebSocket, voice_service: "VoiceService", audio_b64: str, sample_rate: int) -> None:
    """base64 오디오를 디코딩해 백엔드 STT 로 전사하고 결과를 보낸다. 실패도 결과 메시지로 돌려준다."""
    try:
        audio_bytes = base64.b64decode(audio_b64)
        text = await voice_service.transcribe(audio_bytes, sample_rate)
        await ws.send_json({"type": "voice_stt_result", "text": text})
    except Exception as exc:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "voice_stt_result", "text": "", "error": str(exc)})


async def run_tts(ws: WebSocket, voice_service: "VoiceService", text: str, lang: str) -> None:
    """서버 TTS 결과를 보낸다. 브라우저 TTS 프로바이더면 빈 data 와 원문을 돌려 화면이 직접 읽게 한다."""
    try:
        audio_bytes = await voice_service.synthesize(text, lang)
        if audio_bytes:
            await ws.send_json({
                "type": "voice_tts_audio",
                "data": base64.b64encode(audio_bytes).decode(),
                "mime": "audio/wav",
            })
        else:
            await ws.send_json({"type": "voice_tts_audio", "data": "", "text": text})
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
