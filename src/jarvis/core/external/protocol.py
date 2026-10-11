"""[core] 외부 소스의 기본 클래스. 주기마다 외부 세계를 한 번 훑어 이벤트 목록을 돌려준다."""

from jarvis.core.external.types import ExternalEvent

DEFAULT_INTERVAL_SEC = 300.0


class ExternalSource:
    """MCP 가 아닌 소스(웹훅, 파일 감시, 사내 API)도 이 클래스를 이어받아 같은 자리에 꽂힌다.

    poll() 은 예외를 던지지 않는 것을 권장한다(폴러도 격리하지만 소스 단위가 우선).
    기본 구현은 아무것도 감지하지 않는 빈 소스다.
    """

    name: str
    interval_sec: float

    def __init__(self, name: str = "", interval_sec: float = DEFAULT_INTERVAL_SEC) -> None:
        self.name = name
        self.interval_sec = interval_sec

    async def poll(self) -> list[ExternalEvent]:
        return []
