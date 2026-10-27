"""성찰 테스트용 open-loop 저장소. 열린 약속 하나가 늘 있어 성찰이 '말할 근거 없음' 으로 건너뛰지 않는다."""

from jarvis.agent_layer.openloop import InMemoryOpenLoopStore, OpenLoop

GROUND = OpenLoop(description="15시 회의 자료 보내기", origin_session="test")


class GroundedLoopStore(InMemoryOpenLoopStore):
    async def list_open(self, session_id: str | None = None, limit: int = 20) -> list[OpenLoop]:
        return [GROUND, *await super().list_open(session_id=session_id, limit=limit)]
