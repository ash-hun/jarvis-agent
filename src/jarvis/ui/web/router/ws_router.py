"""[ui] /ws 라우트: 연결 하나의 수명(인증, connected 핸드셰이크, 메시지 분기, 정리)을 맡는다."""

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from jarvis.core.focus.types import parse_command
from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope
from jarvis.ui.web.router.agent_router import agent_summary
from jarvis.ui.web.session_registry import UnknownAgent
from jarvis.ui.web.web_auth import auth_enabled, lookup_api_user
from jarvis.ui.web.web_state import WebState
from jarvis.ui.web.ws_tasks import (
    first_feedback,
    run_focus,
    run_prompt,
    run_reply_classify,
    run_stt,
    run_tts,
)

# 키 불일치로 서버가 끊을 때의 close code. 브라우저가 이 코드를 보고 키 입력을 띄운다
WS_UNAUTHORIZED = 4401
# 정의에 없는 에이전트로 새 세션을 열려 할 때. 브라우저는 재연결하지 않고 오류를 보인다
WS_UNKNOWN_AGENT = 4404
DEFAULT_STT_SAMPLE_RATE = 16000


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
        from jarvis.config import ApiUser
        from jarvis.ui.web.adapter import PerConnectionAdapter

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
                msg = await ws.receive_json()
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
                    text = msg.get("text", "").strip()
                    lang = msg.get("lang", settings.voice.tts_lang)
                    if text and voice_service:
                        asyncio.create_task(run_tts(ws, voice_service, text, lang))
                    elif text:
                        # 음성 서비스가 없으면 브라우저가 직접 읽게 돌려준다. 안 주면 HUD 가 '음성 처리 중' 에 멈춘다
                        await ws.send_json({"type": "voice_tts_audio", "data": "", "text": text})

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
