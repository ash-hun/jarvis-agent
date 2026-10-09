from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from jarvis.memory.scope import LOCAL_USER, MemoryScope, current_scope

if TYPE_CHECKING:
    from jarvis.config import ApiUser, BrandConfig, JarvisSettings
    from jarvis.core.session import AgentSession
    from jarvis.ui.tui.startup import AppContext
    from jarvis.voice.service import VoiceService

STATIC_DIR = Path(__file__).parent / "static"
# 키 불일치로 서버가 끊을 때의 close code. 브라우저가 이 코드를 보고 키 입력을 띄운다.
WS_UNAUTHORIZED = 4401


def _auth_enabled(settings: JarvisSettings) -> bool:
    """접근 키가 하나라도 설정돼 있으면 web 인증을 켠다. 비어 있으면 지금처럼 NoAuth."""
    return bool(settings.security.api_keys)


def _lookup_api_user(settings: JarvisSettings, token: str | None) -> ApiUser | None:
    if not token:
        return None
    return settings.security.api_keys.get(token)


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value else None


class SessionManager:
    """세션별 독립 sandbox/pipeline을 생성하여 다중 세션을 관리한다."""

    def __init__(self, ctx: AppContext, base_extra: dict[str, Any]) -> None:
        self._ctx = ctx
        self._base_extra = base_extra
        self._sessions: dict[str, AgentSession] = {}
        self._sandboxes: dict[str, Any] = {}
        # 최근 사용자 활동 시각(monotonic) — 외부 이벤트를 어느 세션이 소비할지 정렬용.
        self._last_activity: dict[str, float] = {}

    def _make_session_extra(self) -> tuple[dict[str, Any], Any]:
        """세션별 sandbox + pipeline을 새로 생성해 extra 복사본을 반환한다."""
        from jarvis.core.policy.authenticator import ApiKeyAuthenticator, NoAuthAuthenticator
        from jarvis.core.policy.pipeline import SecurityPipeline
        from jarvis.core.policy.policy import AllowAllPolicy
        from jarvis.core.policy.sandbox import DefaultSandbox
        from jarvis.core.policy.validator import DefaultInputValidator

        s = self._ctx.settings
        sandbox = DefaultSandbox(
            dangerous_patterns=s.security.dangerous_commands,
            require_approval_for=s.security.require_approval_for,
        )
        # 접근 키가 있으면 키 → (이름, roles) 로 사용자를 식별한다. AuthContext.user_id 가 이름이 되어
        # rate limit 과 tool executor 의 사용자별 정책에 그대로 흐른다.
        authenticator: Any = NoAuthAuthenticator()
        if _auth_enabled(s):
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

    def active_sessions(self) -> list[AgentSession]:
        return list(self._sessions.values())

    def touch(self, session_id: str) -> None:
        """사용자 메시지 수신 시점에 호출 — 세션 recency를 갱신한다."""
        self._last_activity[session_id] = time.monotonic()

    def sessions_by_recency(self) -> list[AgentSession]:
        """최근 활동순 세션 목록. 한 번도 touch되지 않았으면 삽입 순서 폴백.

        외부 이벤트는 inbox drain-once라 첫 세션이 전부 소비한다 — 그 "첫 세션"을
        가장 최근에 대화한 세션으로 만든다.
        """
        items = list(self._sessions.items())
        items.sort(key=lambda kv: self._last_activity.get(kv[0], float("-inf")), reverse=True)
        return [session for _, session in items]

    async def save_all_sessions(self, session_repo: Any, memory: Any, model: Any) -> None:
        """서버 종료 시 모든 활성 세션의 에피소딕 요약을 각 세션의 범위로 저장한다."""
        from jarvis.memory.consolidation.episodic import EpisodicSummarizer

        summarizer = EpisodicSummarizer(model=model, memory=memory)
        for session_id, session in list(self._sessions.items()):
            try:
                msgs = await session_repo.get_messages(session._session_id)
                if not msgs:
                    continue
                scope = getattr(session, "memory_scope", None)
                entry_id = await summarizer.save_session(session._session_id, msgs, scope=scope)
                if entry_id:
                    print(f"[Episodic] Session {session_id[:8]} summary saved (id: {entry_id[:8]})")
                facts = await memory.consolidate(scope)
                if facts:
                    print(f"[Memory] Session {session_id[:8]}: {facts} fact(s) consolidated")
            except Exception as exc:
                print(f"[Episodic] Session {session_id[:8]} summary failed (non-fatal): {exc}")


def create_app(
    ctx: AppContext,
    base_extra: dict[str, Any],
    initial_session_id: str = "default",
) -> FastAPI:
    app = FastAPI(title="Jarvis HUD", docs_url=None, redoc_url=None)
    manager = SessionManager(ctx, base_extra)
    proactive_daemon: Any = None

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

    @app.middleware("http")
    async def _require_api_key(request: Request, call_next: Any) -> Any:
        # /api/* 만 보호한다. 정적 셸(index, js, css)은 키 없이 받아야 키 입력 화면이 뜬다.
        if request.url.path.startswith("/api/") and _auth_enabled(ctx.settings):
            token = _bearer(request.headers.get("authorization")) or request.query_params.get("token")
            if _lookup_api_user(ctx.settings, token) is None:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    @app.on_event("startup")
    async def _startup() -> None:
        nonlocal proactive_daemon
        await manager.get_or_create(initial_session_id)
        if ctx.scheduler is not None:
            await ctx.scheduler.start()

        # Proactivity Daemon (B3) — 매 틱 활성 세션 전체를 성찰 (멀티세션 추종).
        pcfg = ctx.settings.proactive
        if pcfg.daemon_enabled:
            from jarvis.core.proactive import ProactivityDaemon

            proactive_daemon = ProactivityDaemon(
                lambda: [s.reflect for s in manager.sessions_by_recency()],
                interval_sec=pcfg.daemon_interval_sec,
                trigger=ctx.reflection_trigger,
            )
            await proactive_daemon.start()

        # 외부 이벤트 폴러(Phase 3) — 소스 YAML이 없으면 ctx.external_poller가 None.
        if ctx.external_poller is not None:
            await ctx.external_poller.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        if proactive_daemon is not None:
            await proactive_daemon.stop()
        if ctx.external_poller is not None:
            await ctx.external_poller.stop()
        memory = base_extra.get("memory")
        model = base_extra.get("model_config")
        if memory is None or model is None:
            return
        await manager.save_all_sessions(ctx.session_repo, memory, model)

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

    # ── 스케줄 알림 방송 ──────────────────────────────────────────────────────
    # 스케줄 실행 결과를 열린 HUD 전부에 보낸다. 열린 HUD 가 없으면 최근 20건을 쌓아
    # 두었다가 다음 접속 때 missed 로 보낸다(메모리에만 — 서버 재시작 시 사라진다).
    live_clients: set[Any] = set()
    pending_notices: deque[dict[str, Any]] = deque(maxlen=20)

    async def broadcast_notice(payload: dict[str, Any]) -> None:
        if not live_clients:
            pending_notices.append(payload)
            return
        for adapter in list(live_clients):
            await adapter.send(payload)

    if ctx.scheduler is not None:
        ctx.scheduler.set_notifier(broadcast_notice)

    # ── REST: Agenda(스케줄 + open loops) / 도구 ─────────────────────────────
    # HUD 오른쪽 카드가 쓴다. 변경 이벤트가 따로 없으므로 프론트가 접속·응답 종료·
    # 조작 직후에 다시 불러온다.

    @app.get("/api/agenda")  # type: ignore[untyped-decorator]
    async def get_agenda() -> JSONResponse:
        schedules: list[dict[str, Any]] = []
        if ctx.scheduler is not None:
            from jarvis.core.scheduler.service import SchedulerService

            now = datetime.now()
            for task in ctx.scheduler.list_tasks():
                nxt = SchedulerService.next_run(task, now)
                schedules.append({
                    "name": task.name,
                    "description": task.description,
                    "prompt": task.prompt[:160],
                    "schedule": task.schedule,
                    "kind": task.kind,
                    "once": task.run_at is not None,
                    "enabled": task.enabled,
                    # 서버 로컬 시간대 오프셋을 붙인다 — 브라우저가 어느 시간대에 있든 같은 순간을 가리키게
                    "next_run": nxt.astimezone().isoformat() if nxt else None,
                    "run_until": task.run_until.astimezone().isoformat() if task.run_until else None,
                })
            # 곧 돌 작업이 위로, 다음 실행이 없는(꺼짐·만료) 작업은 아래로
            schedules.sort(key=lambda t: (t["next_run"] is None, t["next_run"] or "", t["name"]))

        loops: list[dict[str, Any]] = []
        store = base_extra.get("openloop_store")
        if store is not None:
            for loop in await store.list_open(limit=20):
                loops.append({
                    "id": loop.id,
                    "description": loop.description,
                    "due_ms": loop.due_ms,
                    "created_at": loop.created_at,
                    "origin_session": loop.origin_session,
                })
        return JSONResponse({"schedules": schedules, "open_loops": loops})

    @app.post("/api/openloops/{loop_id}")  # type: ignore[untyped-decorator]
    async def update_openloop(loop_id: str, payload: dict[str, Any]) -> JSONResponse:
        status = payload.get("status")
        if status not in ("done", "dismissed"):
            return JSONResponse({"error": "status must be 'done' or 'dismissed'"}, status_code=400)
        store = base_extra.get("openloop_store")
        if store is None or not await store.update_status(loop_id, status):
            return JSONResponse({"error": "open loop not found"}, status_code=404)
        return JSONResponse({"id": loop_id, "status": status})

    @app.post("/api/schedules/{name}")  # type: ignore[untyped-decorator]
    async def toggle_schedule(name: str, payload: dict[str, Any]) -> JSONResponse:
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            return JSONResponse({"error": "enabled must be true or false"}, status_code=400)
        if ctx.scheduler is None or not ctx.scheduler.set_enabled(name, enabled):
            return JSONResponse({"error": "schedule not found"}, status_code=404)
        return JSONResponse({"name": name, "enabled": enabled})

    @app.get("/api/tools")  # type: ignore[untyped-decorator]
    async def list_tools() -> JSONResponse:
        needs_approval = set(ctx.settings.security.require_approval_for)
        tools = [
            {
                "name": tool.name,
                "description": (tool.description or "").strip().split("\n")[0][:160],
                "approval": tool.name in needs_approval,
            }
            for tool in sorted(ctx.tool_registry.list_all(), key=lambda t: t.name)
        ]
        return JSONResponse({"tools": tools})

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
        token: str | None = Query(default=None),
    ) -> None:
        from jarvis.ui.web.adapter import PerConnectionAdapter

        # accept 뒤에 닫아야 브라우저가 close code(4401)를 읽을 수 있다. accept 전에 닫으면 403 으로만 보인다.
        await ws.accept()
        user: ApiUser | None = None
        if _auth_enabled(ctx.settings):
            user = _lookup_api_user(ctx.settings, token)
            if user is None:
                await ws.close(code=WS_UNAUTHORIZED, reason="invalid token")
                return
        credentials = {"api_key": token} if user is not None else {}
        session, sandbox = await manager.get_or_create(session_id)

        adapter = PerConnectionAdapter(ws)
        sandbox.set_approval_callback(adapter.request_approval)
        unsubscribe = session.subscribe(adapter.on_agent_event)

        try:
            stt_browser = voice_service is None or voice_service.stt_is_browser
            await ws.send_json({
                "type": "connected",
                "session_id": session._session_id,
                "user": user.name if user is not None else None,
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

            # 스케줄 알림 방송 대상에 넣고, 아무도 없을 때 쌓인 알림을 먼저 보낸다
            live_clients.add(adapter)
            while pending_notices:
                await adapter.send({**pending_notices.popleft(), "missed": True})

            while True:
                msg = await ws.receive_json()
                msg_type = msg.get("type", "")

                if msg_type == "user_message":
                    text = msg.get("text", "").strip()
                    if text:
                        manager.touch(session_id)
                        # 슬래시 명령 인터셉트 — 텍스트 어디서나 /command 처리 후 나머지만 LLM으로 전달
                        if ctx.dispatcher is not None:
                            # /remember 같은 명령이 이 연결의 사용자 범위로 기억을 쓰게 한다
                            current_scope.set(MemoryScope(
                                user_id=user.name if user is not None else LOCAL_USER,
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
                            asyncio.create_task(_run_prompt(session, adapter, text, credentials))

                elif msg_type == "approval_response":
                    await adapter.handle_approval_response(
                        approval_id=msg.get("id", ""),
                        approved=bool(msg.get("approved", False)),
                    )

                elif msg_type == "proactive_feedback":
                    # proactive 발화 수락/무시 → 피드백 학습기 (C3).
                    await session.record_feedback(bool(msg.get("accepted", False)))

                elif msg_type == "voice_tts_request":
                    text = msg.get("text", "").strip()
                    lang = msg.get("lang", ctx.settings.voice.tts_lang)
                    if text and voice_service:
                        asyncio.create_task(_run_tts(ws, voice_service, text, lang))
                    elif text:
                        # 음성 서비스가 없으면 브라우저가 직접 읽게 돌려준다 — 응답이 없으면
                        # HUD 가 '음성 처리 중' 상태에 멈춘다
                        await ws.send_json({"type": "voice_tts_audio", "data": "", "text": text})

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
            live_clients.discard(adapter)
            unsubscribe()

    # ── 브랜드: 에이전트별 워드마크·명언·색감 ────────────────────────────────
    # 정적 셸은 에이전트와 무관하게 두고, 정체성은 이 두 라우트로만 주입한다.

    @app.get("/brand.js")  # type: ignore[untyped-decorator]
    async def brand_js() -> Response:
        return Response(
            render_brand_js(ctx.settings.brand),
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/manifest.json")  # type: ignore[untyped-decorator]
    async def manifest() -> JSONResponse:
        return JSONResponse(render_manifest(ctx.settings.brand))

    # static 파일 서빙 — WebSocket 라우트 등록 후 마운트
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


def render_brand_js(brand: BrandConfig) -> str:
    """<head>에서 동기 로드되는 스크립트. 첫 페인트 전에 CSS 변수와 window.BRAND를 채운다."""
    payload = json.dumps(brand.model_dump(), ensure_ascii=False)
    return (
        f"window.BRAND = {payload};\n"
        "(function (p) {\n"
        "  var s = document.documentElement.style;\n"
        "  s.setProperty('--primary', p.primary);\n"
        "  s.setProperty('--accent', p.accent);\n"
        "  s.setProperty('--bg-0', p.background);\n"
        "  p.nebula.forEach(function (c, i) { s.setProperty('--nebula-' + i, c); });\n"
        "})(window.BRAND.palette);\n"
    )


def render_manifest(brand: BrandConfig) -> dict[str, Any]:
    """정적 manifest.json을 바탕으로 이름·색만 에이전트 것으로 바꾼다."""
    manifest: dict[str, Any] = json.loads((STATIC_DIR / "manifest.json").read_text("utf-8"))
    manifest["name"] = f"{brand.name} · HUD"
    manifest["short_name"] = brand.name
    manifest["background_color"] = brand.palette.background
    manifest["theme_color"] = brand.palette.background
    return manifest


async def _run_prompt(session: Any, adapter: Any, text: str, credentials: dict[str, Any]) -> None:
    try:
        await session.prompt(text, credentials=credentials)
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
