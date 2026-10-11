"""[memory] 테스트와 in_memory 설정용 작업 기억 저장소."""

from jarvis.memory.working.state import WorkingStore


class InMemoryWorkingStore(WorkingStore):
    """기반 클래스의 dict 동작을 그대로 쓴다. 설정값 in_memory 와 짝을 맞춘 이름이다."""
