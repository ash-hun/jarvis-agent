"""[ui] /ws 라우트: 연결 하나의 수명(인증, connected 핸드셰이크, 메시지 분기, 정리)을 맡는다."""

import json
import asyncio
from typing import Any
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from jarvis.ui.web.ws_tasks import (
    first_feedback,
    run_focus,
    run_prompt,
    run_reply_classify,
    run_stt,
    run_tts,
)
from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope
from jarvis.ui.web.web_auth import auth_enabled, lookup_api_user
from jarvis.ui.web.router.agent_router import agent_summary
from jarvis.ui.web.session_registry import UnknownAgent
from jarvis.core.focus.types import parse_command
from jarvis.voice.speech_text import speech_text
from jarvis.ui.web.web_state import WebState
from jarvis.common.logger import get_logger
from jarvis.voice.wake import WakeDetector

# 키 불일치로 서버가 끊을 때의 close code. 브라우저가 이 코드를 보고 키 입력을 띄운다
WS_UNAUTHORIZED = 4401
# 정의에 없는 에이전트로 새 세션을 열려 할 때. 브라우저는 재연결하지 않고 오류를 보인다
WS_UNKNOWN_AGENT = 4404
DEFAULT_STT_SAMPLE_RATE = 16000

logger = get_logger(__name__)


async def receive_frame(ws: WebSocket) -> dict[str, Any] | bytes:
    """텍스트 프레임은 JSON 메시지로, 바이너리 프레임은 웨이크워드용 PCM 으로 돌려준다. 끊기면 WebSocketDisconnect."""
    message = await ws.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    data = message.get("bytes")
    if data is not None:
        return bytes(data)
    parsed: dict[str, Any] = json.loads(message.get("text") or "{}")
    return parsed


def build_ws_router(state: WebState) -> APIRouter:
    router = APIRouter()
    ctx = state.ctx
    settings = state.settings

    @router.websocket("/ws")
    async def websocket_endpoint(
        ws: WebSocket,
        session_id: str = Query(default="default", description="붙을 세션 id. 없으면 만든다"),
        token: str | None = Query(default=None, description="접근 키. 인증이 켜져 있을 때만 필요"),
        agent: str | None = Query(
            default=None, description="새 세션을 맡을 에이전트 id. 이미 있는 세션은 저장된 에이전트로 열린다"
        ),
    ) -> None:
        from jarvis.ui.web.adapter import PerConnectionAdapter
        from jarvis.config import ApiUser

        # accept 뒤에 닫아야 브라우저가 close code(4401)를 읽을 수 있다. accept 전에 닫으면 403 으로만 보인다
        await ws.accept()
        user: ApiUser | None = None
        if auth_enabled(settings):
            user = lookup_api_user(settings, token)
            if user is None:
                await ws.close(code=WS_UNAUTHORIZED, reason="invalid token")
                return
        credentials = {"api_key": token} if user is not None and token is not None else {}
        try:
            session, sandbox = await state.registry.get_or_create(session_id, agent)
        except UnknownAgent as exc:
            await ws.close(code=WS_UNKNOWN_AGENT, reason=f"unknown agent: {exc}")
            return
        agent_id = state.registry.agent_of(session_id)
        profile = state.assembly.agents.builder(agent_id).profile

        adapter = PerConnectionAdapter(ws)
        broker = state.broker(session_id)
        await broker.attach(adapter)
        sandbox.set_approval_callback(broker.request)
        unsubscribe = session.subscribe(adapter.on_agent_event)
        # 같은 🔔 에 피드백이 두 번 와도(재전송, 키워드와 분류가 겹침) 학습은 한 번만
        feedback_ids: set[str] = set()
        voice_service = state.voice_service
        # 웨이크워드 감지기는 첫 오디오가 올 때 만든다. 만들다 실패하면 이 연결에서는 다시 시도하지 않는다
        wake_detector: WakeDetector | None = None
        wake_on = state.wake is not None

        try:
            stt_browser = voice_service is None or voice_service.stt_is_browser
            await ws.send_json({
                "type": "connected",
                "session_id": session._session_id,
                "agent": agent_summary(profile),
                "user": user.name if user is not None else None,
                "model": session._harness._model.model,
                "sessions": state.registry.list_ids(),
                "session_agents": state.registry.session_agents(),
                "active_agents": state.activity.active(),
                "slash_commands": [
                    {"name": name, "description": desc} for name, desc in sorted(ctx.dispatcher.commands.items())
                ] if ctx.dispatcher else [],
                "voice": {
                    # server: 브라우저가 녹음해 백엔드 STT 로 보낸다. browser: Web Speech API 가 인식까지
                    "stt_mode": "browser" if stt_browser else "server",
                    "stt_lang": settings.voice.stt_lang,
                    # 미리 녹음한 문구 이름. 화면은 이 이름만 /api/voice/phrases/{name} 으로 받는다
                    "phrases": sorted(state.phrases),
                    # true 면 Full-voice 대기 중에 16kHz PCM 을 바이너리 프레임으로 보내고 voice_wake 를 기다린다
                    "wake": wake_on,
                },
                "reply_classifier": state.reply_classifier is not None,
            })

            # 스케줄 알림 방송 대상에 넣고, 아무도 없을 때 쌓인 알림을 먼저 보낸다
            state.live_clients.add(adapter)
            while state.pending_notices:
                await adapter.send({**state.pending_notices.popleft(), "missed": True})

            # 진행 중인 Focus 작업이 있으면(재시작 뒤 포함) 화면을 Focus 로 되살린다
            if state.focus is not None:
                run = await state.focus.restore(session)
                for event in run.panel_events() if run is not None else []:
                    await adapter.on_agent_event(event)

            while True:
                frame = await receive_frame(ws)
                if isinstance(frame, bytes):
                    if not wake_on or state.wake is None:
                        continue
                    if wake_detector is None:
                        try:
                            wake_detector = await asyncio.to_thread(state.wake)
                        except Exception as exc:
                            logger.warning(f"[Voice] 웨이크워드 감지기 생성 실패, 이 연결에서 끈다: {exc}")
                            wake_on = False
                            continue
                    score = wake_detector.feed(frame)
                    if score is not None:
                        await ws.send_json({"type": "voice_wake", "score": round(score, 3)})
                    continue
                msg = frame
                msg_type = msg.get("type", "")

                if msg_type == "user_message":
                    text = msg.get("text", "").strip()
                    if text:
                        state.registry.touch(session_id)
                        focus_command = parse_command(text) if state.focus is not None else None
                        if state.focus is not None and focus_command is not None:
                            current_scope.set(MemoryScope(
                                user_id=user.name if user is not None else LOCAL_USER,
                                agent_id=agent_id,
                                session_id=session_id,
                            ))
                            asyncio.create_task(
                                run_focus(session, adapter, state.focus, focus_command, credentials)
                            )
                            continue
                        # 슬래시 명령 인터셉트: 텍스트 어디서나 /command 를 처리하고 나머지만 LLM 으로 보낸다
                        if ctx.dispatcher is not None:
                            # /remember 같은 명령이 이 연결의 사용자 범위로 기억을 쓰게 한다
                            current_scope.set(MemoryScope(
                                user_id=user.name if user is not None else LOCAL_USER,
                                agent_id=agent_id,
                                session_id=session_id,
                            ))
                            result = await ctx.dispatcher.dispatch(text)
                            for feedback in result.feedbacks:
                                await ws.send_json({"type": "agent_start"})
                                await ws.send_json({"type": "stream_delta", "text": feedback})
                                await ws.send_json({"type": "agent_end"})
                            if result.fully_consumed:
                                continue
                            text = result.remaining_text
                        if text.strip():
                            asyncio.create_task(run_prompt(session, adapter, text, credentials))

                elif msg_type == "approval_response":
                    broker.resolve(
                        approval_id=msg.get("id", ""),
                        approved=bool(msg.get("approved", False)),
                        always=bool(msg.get("always", False)),
                    )

                elif msg_type == "proactive_feedback":
                    # 🔔 수락/무시 → 피드백 학습기
                    if first_feedback(feedback_ids, msg.get("id")):
                        await session.record_feedback(bool(msg.get("accepted", False)))

                elif msg_type == "reply_classify":
                    asyncio.create_task(run_reply_classify(ws, state.reply_classifier, session, feedback_ids, msg))

                elif msg_type == "voice_tts_request":
                    text = speech_text(msg.get("text", ""))
                    lang = msg.get("lang", settings.voice.tts_lang)
                    # 화면이 멈춘 읽기의 늦은 응답을 버릴 수 있게 요청 id 를 그대로 돌려준다
                    request_id = msg.get("id")
                    if text and voice_service:
                        asyncio.create_task(run_tts(ws, voice_service, text, lang, request_id))
                    else:
                        # 음성 서비스가 없거나 읽을 글자가 없어도 답한다. 안 주면 HUD 가 '음성 처리 중' 에 멈춘다
                        await ws.send_json({"type": "voice_tts_audio", "data": "", "text": text, "id": request_id})

                elif msg_type == "voice_stt_submit":
                    data = msg.get("data", "")
                    sample_rate = int(msg.get("sample_rate", DEFAULT_STT_SAMPLE_RATE))
                    if data and voice_service:
                        asyncio.create_task(run_stt(ws, voice_service, data, sample_rate))

                elif msg_type == "abort":
                    session.abort()

        except WebSocketDisconnect:
            pass
        finally:
            state.live_clients.discard(adapter)
            broker.detach(adapter)
            unsubscribe()

    return router
