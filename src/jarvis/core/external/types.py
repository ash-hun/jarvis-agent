from __future__ import annotations

from pydantic import BaseModel


class ExternalEvent(BaseModel):
    """외부 세계(캘린더·메일 등)에서 새로 감지한 사실 1건.

    벤더 스키마를 해석하지 않는다 — 원문을 그대로 실어 나르고, 의미 부여는
    inner thought LLM이 한다(설계 §2 "원문 패스스루").
    """

    source: str  # YAML의 소스 이름 (예: "calendar-upcoming")
    key: str  # dedup 키 ("calendar-upcoming:abc123")
    title: str = ""  # 한 줄 요약 (추론 가능하면)
    detail: str = ""  # 원문 (detail_max_chars로 절단)
    occurred_at: str = ""  # best-effort ISO 문자열, 없으면 빈 값

    def as_line(self, include_detail: bool = True) -> str:
        """사고 프롬프트에 넣을 한 줄.

        include_detail=False면 원문을 싣지 않는다(프라이버시) — 제목만으로 판단하게
        한다. 다만 제목을 추론하지 못한 소스(비정형 원문)는 제목 대신 원문으로
        폴백한다: 그마저 없으면 이벤트가 키만 남아 판단 불가가 되기 때문이다.
        """
        stamp = f" ({self.occurred_at})" if self.occurred_at else ""
        title = _one_line(self.title)
        detail = _one_line(self.detail)
        if not include_detail:
            return f"[{self.source}]{stamp} {title or detail or self.key}"
        head = title or detail or self.key
        if title and detail and detail != head:
            head = f"{head} — {detail}"
        return f"[{self.source}]{stamp} {head}"


def _one_line(text: str, max_chars: int = 300) -> str:
    flat = " ".join(str(text).split())
    return flat[:max_chars]
