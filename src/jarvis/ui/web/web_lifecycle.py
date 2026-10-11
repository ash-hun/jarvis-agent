"""[ui] Web HUD 기동과 종료: 첫 세션, 스케줄러, 성찰 daemon, 외부 이벤트 폴러를 켜고 끄고 세션을 저장한다."""

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from jarvis.ui.web.web_state import WebState

if TYPE_CHECKING:
    from jarvis.core.proactive import ProactivityDaemon


class WebLifecycle:
    """FastAPI startup/shutdown 훅이 부른다. start 와 stop 은 한 번씩 짝으로 불린다고 본다."""

    def __init__(self, state: WebState, initial_session_id: str) -> None:
        self._state = state
        self._initial_session_id = initial_session_id
        self._daemon: ProactivityDaemon | None = None
        ctx = state.ctx
        if ctx.scheduler is not None:
            from jarvis.core.notify import fan_out

            # 화면 방송 + 외부 채널(있으면). 둘 중 하나가 실패해도 다른 쪽은 받는다
            ctx.scheduler.set_notifier(fan_out(state.broadcast_notice, ctx.notifier))

    async def start(self) -> None:
        state, ctx = self._state, self._state.ctx
        await state.registry.get_or_create(self._initial_session_id)
        if ctx.scheduler is not None:
            await ctx.scheduler.start()

        # 성찰 daemon: 매 틱 활성 세션 전체를 성찰한다(멀티 세션 추종)
        pcfg = state.settings.proactive
        if pcfg.daemon_enabled:
            from jarvis.core.proactive import ProactivityDaemon
            from jarvis.memory.consolidation.idle import consolidation_targets, should_consolidate_on_idle

            memory = state.assembly.services.memory
            consolidate = should_consolidate_on_idle(state.settings)

            def targets() -> list[Callable[[], Awaitable[object]]]:
                sessions = state.registry.sessions_by_recency()
                reflects: list[Callable[[], Awaitable[object]]] = [s.reflect for s in sessions]
                # 성찰 뒤에 공고화. 같은 틱에서 먼저 말할지 정한 다음 조용히 기억을 정리한다
                return reflects + (consolidation_targets(memory, sessions) if consolidate else [])

            self._daemon = ProactivityDaemon(
                targets, interval_sec=pcfg.daemon_interval_sec, trigger=ctx.reflection_trigger
            )
            await self._daemon.start()

        # 외부 이벤트 폴러. 소스 YAML 이 없으면 None
        if ctx.external_poller is not None:
            await ctx.external_poller.start()

    async def stop(self) -> None:
        state, ctx = self._state, self._state.ctx
        if self._daemon is not None:
            await self._daemon.stop()
        if ctx.external_poller is not None:
            await ctx.external_poller.stop()
        services = state.assembly.services
        await state.registry.save_all_sessions(ctx.session_repo, services.memory, services.model_config)
