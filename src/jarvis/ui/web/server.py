from __future__ import annotations

import asyncio
import base64
import contextlib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

if TYPE_CHECKING:
    from jarvis.core.session import AgentSession
    from jarvis.ui.tui.startup import AppContext
    from jarvis.voice.service import VoiceService

STATIC_DIR = Path(__file__).parent / "static"


class SessionManager:
    """세션별 독립 sandbox/pipeline을 생성하여 다중 세션을 관리한다."""

    def __init__(self, ctx: AppContext, base_extra: dict[str, Any]) -> None:
        self._ctx = ctx
        self._base_extra = base_extra
        self._sessions: dict[str, AgentSession] = {}
        self._sandboxes: dict[str, Any] = {}

    def _make_session_extra(self) -> tuple[dict[str, Any], Any]:
        """세션별 sandbox + pipeline을 새로 생성해 extra 복사본을 반환한다."""
        from jarvis.core.policy.authenticator import NoAuthAuthenticator
        from jarvis.core.policy.pipeline import SecurityPipeline
        from jarvis.core.policy.policy import AllowAllPolicy
        from jarvis.core.policy.sandbox import DefaultSandbox
        from jarvis.core.policy.validator import DefaultInputValidator

        s = self._ctx.settings
        sandbox = DefaultSandbox(
            dangerous_patterns=s.security.dangerous_commands,
            require_approval_for=s.security.require_approval_for,
        )
        pipeline = SecurityPipeline(
            validator=DefaultInputValidator(max_length=s.security.input_max_length),
            authenticator=NoAuthAuthenticator(),
            policy=AllowAllPolicy(),
            sandbox=sandbox,
        )
        return {**self._base_extra, "pipeline": pipeline, "sandbox": sandbox}, sandbox

    async def get_or_create(self, session_id: str) -> tuple[AgentSession, Any]:
        if session_id not in self._sessions:
            from jarvis.ui.tui.startup import _build_agent_session
            await self._ctx.session_repo.create(session_id=session_id)
            extra, sandbox = self._make_session_extra()
            self._sessions[session_id] = _build_agent_session(session_id, self._ctx, extra)
            self._sandboxes[session_id] = sandbox
        return self._sessions[session_id], self._sandboxes[session_id]

    async def create_new(self) -> str:
        sid = uuid.uuid4().hex[:8]
        await self.get_or_create(sid)
        return sid

    def list_ids(self) -> list[str]:
        return list(self._sessions.keys())

    async def save_all_sessions(self, stm: Any, ltm: Any, model: Any) -> None:
        """서버 종료 시 모든 활성 세션의 에피소딕 요약을 LTM에 저장한다."""
        from jarvis.agent_layer.memory.episodic import EpisodicSummarizer

        summarizer = EpisodicSummarizer(model=model, ltm_backend=ltm)
        for session_id, session in list(self._sessions.items()):
            try:
                msgs = await stm.load(session._session_id)
                if not msgs:
                    continue
                entry_id = await summarizer.save_session(session._session_id, msgs)
                if entry_id:
                    print(f"[Episodic] Session {session_id[:8]} summary saved (id: {entry_id[:8]})")
            except Exception as exc:
                print(f"[Episodic] Session {session_id[:8]} summary failed (non-fatal): {exc}")


def create_app(
    ctx: AppContext,
    base_extra: dict[str, Any],
    initial_session_id: str = "default",
) -> FastAPI:
    app = FastAPI(title="Jarvis HUD", docs_url=None, redoc_url=None)
    manager = SessionManager(ctx, base_extra)

    # Voice service — lazy init from config
    voice_service: VoiceService | None = None
    try:
        from jarvis.voice.service import VoiceService as _VS
        v = ctx.settings.voice
        voice_service = _VS.from_config(
            stt_provider=v.stt_provider,
            tts_provider=v.tts_provider,
        )
    except Exception:
        pass

    @app.on_event("startup")
    async def _startup() -> None:
        await manager.get_or_create(initial_session_id)
        if ctx.scheduler is not None:
            await ctx.scheduler.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        stm = base_extra.get("stm_backend")
        ltm = base_extra.get("ltm_backend")
        model = base_extra.get("model_config")
        if stm is None or ltm is None or model is None:
            return
        await manager.save_all_sessions(stm, ltm, model)

    # ── REST: 세션 목록 / 생성 / 히스토리 ────────────────────────────────────

    @app.get("/api/sessions")  # type: ignore[untyped-decorator]
    async def list_sessions() -> JSONResponse:
        return JSONResponse({"sessions": manager.list_ids()})

    @app.post("/api/sessions")  # type: ignore[untyped-decorator]
    async def create_session() -> JSONResponse:
        sid = await manager.create_new()
        return JSONResponse({"session_id": sid})

    @app.post("/api/sessions/{session_id}/branch")  # type: ignore[untyped-decorator]
    async def branch_session(session_id: str) -> JSONResponse:
        from jarvis.agent_layer.session.jsonl import JsonlSessionRepo
        repo = ctx.session_repo
        if isinstance(repo, JsonlSessionRepo):
            meta = await repo.create_branch(session_id)
        else:
            new_sid = await manager.create_new()
            return JSONResponse({"session_id": new_sid, "parent_id": None})
        # Pre-create the AgentSession for the branch
        await manager.get_or_create(meta.session_id)
        return JSONResponse({"session_id": meta.session_id, "parent_id": meta.parent_id})

    @app.get("/api/slash-commands")  # type: ignore[untyped-decorator]
    async def get_slash_commands() -> JSONResponse:
        if ctx.dispatcher is None:
            return JSONResponse({"commands": []})
        cmds = [
            {"name": name, "description": desc}
            for name, desc in sorted(ctx.dispatcher.commands.items())
        ]
        return JSONResponse({"commands": cmds})

    @app.get("/api/sessions/{session_id}/messages")  # type: ignore[untyped-decorator]
    async def get_session_messages(session_id: str) -> JSONResponse:
        messages = await ctx.session_repo.get_messages(session_id)
        result = []
        for msg in messages:
            role = getattr(msg, "role", None)
            if role == "user":
                content = msg.content
                text = content if isinstance(content, str) else "".join(
                    c.text for c in content if hasattr(c, "text")
                )
                if text:
                    result.append({"role": "user", "text": text})
            elif role == "assistant":
                text = msg.text()
                if text:
                    result.append({"role": "assistant", "text": text})
        return JSONResponse({"messages": result})

    # ── WebSocket ─────────────────────────────────────────────────────────────

    @app.websocket("/ws")  # type: ignore[untyped-decorator]
    async def websocket_endpoint(
        ws: WebSocket,
        session_id: str = Query(default="default"),
    ) -> None:
        from jarvis.ui.web.adapter import PerConnectionAdapter

        await ws.accept()
        session, sandbox = await manager.get_or_create(session_id)

        adapter = PerConnectionAdapter(ws)
        sandbox.set_approval_callback(adapter.request_approval)
        unsubscribe = session.subscribe(adapter.on_agent_event)

        try:
            stt_browser = voice_service is None or voice_service.stt_is_browser
            await ws.send_json({
                "type": "connected",
                "session_id": session._session_id,
                "model": session._harness._model.model,
                "sessions": manager.list_ids(),
                "slash_commands": [
                    {"name": name, "description": desc}
                    for name, desc in sorted(ctx.dispatcher.commands.items())
                ] if ctx.dispatcher else [],
                "voice": {
                    # server: 브라우저가 오디오를 녹음해 백엔드 STT(Whisper 등)로 전송
                    # browser: 브라우저 Web Speech API가 인식까지 담당
                    "stt_mode": "browser" if stt_browser else "server",
                    "stt_lang": ctx.settings.voice.stt_lang,
                },
            })

            while True:
                msg = await ws.receive_json()
                msg_type = msg.get("type", "")

                if msg_type == "user_message":
                    text = msg.get("text", "").strip()
                    if text:
                        # 슬래시 명령 인터셉트 — 텍스트 어디서나 /command 처리 후 나머지만 LLM으로 전달
                        if ctx.dispatcher is not None:
                            result = await ctx.dispatcher.dispatch(text)
                            for feedback in result.feedbacks:
                                await ws.send_json({"type": "agent_start"})
                                await ws.send_json({"type": "stream_delta", "text": feedback})
                                await ws.send_json({"type": "agent_end"})
                            if result.fully_consumed:
                                continue
                            text = result.remaining_text
                        if text.strip():
                            asyncio.create_task(_run_prompt(session, adapter, text))

                elif msg_type == "approval_response":
                    await adapter.handle_approval_response(
                        approval_id=msg.get("id", ""),
                        approved=bool(msg.get("approved", False)),
                    )

                elif msg_type == "voice_tts_request":
                    text = msg.get("text", "").strip()
                    lang = msg.get("lang", ctx.settings.voice.tts_lang)
                    if text and voice_service:
                        asyncio.create_task(_run_tts(ws, voice_service, text, lang))

                elif msg_type == "voice_stt_submit":
                    data = msg.get("data", "")
                    sample_rate = int(msg.get("sample_rate", 16000))
                    if data and voice_service:
                        asyncio.create_task(_run_stt(ws, voice_service, data, sample_rate))

                elif msg_type == "abort":
                    session.abort()

        except WebSocketDisconnect:
            pass
        finally:
            unsubscribe()

    # static 파일 서빙 — WebSocket 라우트 등록 후 마운트
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


async def _run_prompt(session: Any, adapter: Any, text: str) -> None:
    try:
        await session.prompt(text)
    except Exception as exc:
        await adapter.show_error(str(exc))


async def _run_stt(ws: Any, voice_service: Any, audio_b64: str, sample_rate: int) -> None:
    """base64 오디오를 디코딩해 백엔드 STT로 전사하고 결과를 전송한다."""
    try:
        audio_bytes = base64.b64decode(audio_b64)
        text = await voice_service.transcribe(audio_bytes, sample_rate)
        await ws.send_json({"type": "voice_stt_result", "text": text})
    except Exception as exc:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "voice_stt_result", "text": "", "error": str(exc)})


async def _run_tts(ws: Any, voice_service: Any, text: str, lang: str) -> None:
    try:
        audio_bytes = await voice_service.synthesize(text, lang)
        if audio_bytes:
            await ws.send_json({
                "type": "voice_tts_audio",
                "data": base64.b64encode(audio_bytes).decode(),
                "mime": "audio/wav",
            })
        else:
            # BrowserTTSProvider — 클라이언트가 Web Speech API로 읽어야 함
            await ws.send_json({
                "type": "voice_tts_audio",
                "data": "",
                "text": text,
            })
    except Exception as exc:
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": f"TTS 오류: {exc}"})
