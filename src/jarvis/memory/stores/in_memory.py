"""[memory] 프로세스가 끝나면 사라지는 테스트와 in_memory 설정용 장기 기억 저장소."""

from jarvis.memory.stores.store_protocol import ItemStore


class InMemoryItemStore(ItemStore):
    """기반 클래스의 dict 동작을 그대로 쓴다. 설정값 in_memory 와 짝을 맞춘 이름이다."""
