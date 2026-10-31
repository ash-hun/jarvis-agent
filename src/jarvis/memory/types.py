"""[memory] 심리학의 장기 기억 분류(일화, 의미, 절차)를 그대로 쓴 메모리 항목의 종류와 데이터 모델."""

import uuid
from typing import Any
from enum import StrEnum
from datetime import datetime
from dataclasses import dataclass, field

from jarvis.memory.scope import MemoryScope

# 상대 지칭("그거", "아까 그 방법")으로 쓴 항목이 가리킨 대화. 검색과 임베딩, 회상 표시에 같이 쓴다
REFERENT = "referent"


class MemoryKind(StrEnum):
    EPISODIC = "episodic"  # 겪은 사건. 시간과 장소(세션, 에이전트)가 붙는다
    SEMANTIC = "semantic"  # 세상과 사용자에 대한 사실. 갱신은 삭제가 아니라 superseded_by 로 잇는다
    PROCEDURAL = "procedural"  # 어떻게 하는지. 스킬과 도구 순서. 실행 가능한 형태로 쓴다


@dataclass
class MemoryItem:
    content: str
    kind: MemoryKind
    scope: MemoryScope
    author: str = "agent"  # "user" | agent_id | "orchestrator"
    source: str = ""  # 쓰기 경로 이름 (explicit, turn, thought, ...)
    importance: float = 0.5  # 0..1. 공고화 후보 선정과 검색 가중치
    tags: list[str] = field(default_factory=list)
    occurred_at: datetime | None = None  # 일화: 사건 시각
    valid_from: datetime | None = None  # 의미: 사실이 유효해진 시각
    superseded_by: str | None = None  # 의미: 이 항목을 대체한 항목 id
    rehearsal_count: int = 0  # 작업 기억에서 참조된 횟수(되뇌기)
    last_accessed: datetime | None = None  # 점화: 최근 회상 시각
    embedding: list[float] | None = None  # 의미 유사도 검색용 벡터. 임베더가 없으면 None
    embedding_model: str | None = None  # 어떤 모델로 만든 벡터인지. 모델이 바뀌면 재임베딩 대상
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        """검색과 임베딩 대상. 본문만으로 뜻이 안 서는 상대 지칭 항목은 가리킨 대화를 덧붙인다."""
        referent = self.metadata.get(REFERENT)
        return f"{self.content}\n{referent}" if referent else self.content

    @property
    def session_id(self) -> str | None:
        return self.scope.session_id
