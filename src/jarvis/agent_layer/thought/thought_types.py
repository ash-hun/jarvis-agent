"""[agent_layer] inner thought 의 입력(ThoughtRequest), 출력(ThoughtFrame), 먼저 할 행동 후보 모델을 정의한다."""

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator

from jarvis.model_layer.model_types import Message


class ProactiveAction(BaseModel):
    """
    inner thought가 "지금 먼저 해두면 좋다"고 판단한 행동 후보.

    Tier 0에서는 채워지되 실행하지 않는다(관찰/로그용).
    Tier 1의 결정 정책이 risk·confidence로 게이팅한 뒤 실행한다.
    """

    kind: Literal["suggest", "tool", "remember", "schedule"]
    description: str  # 사람이 읽을 수 있는 행동 설명
    tool_name: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    risk: Literal["low", "high"] = "low"  # 저위험=자율 후보, 고위험=승인 대상


class ThoughtFrame(BaseModel):
    """
    inner thought 1회의 구조화된 산출물.

    스키마는 안정적으로 유지한다: 사용자는 주로 프롬프트 템플릿을 편집해
    이 프레임이 "채워지는 방식"을 조율한다(필드 자체는 바꾸지 않는다).
    """

    observation: str = ""  # 무엇이 들어왔는가(사실)
    interpretation: str = ""  # 의도 / 감정 / 숨은 니즈 해석
    recalled: list[str] = Field(default_factory=list)  # 회상한 관련 기억 요약
    options: list[str] = Field(default_factory=list)  # 가능한 대응 후보
    proactive_actions: list[ProactiveAction] = Field(default_factory=list)
    decision: Literal["act", "ask", "silent"] = "silent"  # 확신 없으면 silent
    confidence: float = 0.0  # 0.0–1.0
    rationale: str = ""  # 결정 근거(관찰 가능성)
    # 사용자에게 실제로 건넬 말. interpretation 은 사용자를 분석한 3인칭 문장이라 그대로 내보내면 안 된다.
    utterance: str = ""
    # Dual-Channel (Tier 1): 메인 작업이 오래 걸릴 것으로 판단되면 needs_background=True,
    # filler에 "오래 걸린다"를 표현하는 즉답을 담는다(voice/text fast channel용).
    needs_background: bool = False
    filler: str = ""
    # 약속(open loop)은 사고가 아니라 매 턴 따로 도는 AGENDA 판단(openloop.judge)이 잡고 닫는다

    @field_validator("recalled", "options", mode="before")
    @classmethod
    def _items_to_text(cls, value: Any) -> Any:
        return items_to_text(value)

    def context_block(self) -> str:
        """
        메인 턴 system_prompt에 덧붙일 사람이 읽을 수 있는 한 블록.

        대화 히스토리를 오염시키지 않도록 system_prompt 증강 전용으로만 쓴다.
        """
        lines = ["[내적 사고]"]
        if self.interpretation:
            lines.append(f"해석: {self.interpretation}")
        if self.recalled:
            lines.append("회상:")
            lines.extend(f"  - {item}" for item in self.recalled)
        if self.options:
            lines.append("고려한 대응: " + " / ".join(self.options))
        return "\n".join(lines)


class SituationFact(BaseModel):
    """성찰 항목(약속이나 외부 이벤트) 하나에 코드가 미리 계산해 둔 사실. 모르는 값은 None 이다.

    작은 모델은 시각 두 개를 빼다 틀리고 "수락했다" 를 못 보고 지나친다. 계산은 코드가 하고 모델은 판단만 한다.
    """

    text: str
    source: Literal["loop", "event"] = "event"
    days: int | None = None  # 언급된 날짜까지 남은 날(지난 날은 음수)
    minutes: int | None = None  # 언급된 시각까지 남은 분(지난 시각은 음수). 시각이 없으면 None
    signal: str | None = None  # 처리 신호(수락, 완료, 취소, 확인)

    def view(self) -> dict[str, Any]:
        """decision model 에 넘길 모양. 모르는 값은 "unknown" 으로 적어 없는 것과 구분한다."""
        within = None if self.minutes is None else self.minutes <= 30
        return {
            "item": self.text,
            "time_left": when_text(self.days, self.minutes),
            "within_30_min": "unknown" if within is None else within,
            "handled_signal": self.signal or "none",
        }


class ThoughtRequest(BaseModel):
    """
    `ThoughtEngine.think()`의 입력 계약.

    per-call 데이터만 담는다. 필드를 추가해도(예: open_loops 확장) think()
    시그니처는 불변이므로 호출부(session.py / daemon)를 깨지 않는다.
    """

    model_config = {"arbitrary_types_allowed": True}

    user_input: str
    history: list[Message] = Field(default_factory=list)
    session_id: str | None = None
    # 회상할 기억의 주인. 비우면 로컬 사용자의 main 에이전트다
    user_id: str | None = None
    agent_id: str | None = None
    open_loops: list[str] = Field(default_factory=list)  # Tier 2에서 채워짐
    user_model: str = ""  # Tier 3: 증류된 사용자 모델 컨텍스트(주입용)
    # Phase 3: 외부 세계(캘린더·메일 등)에서 새로 감지한 사실의 한 줄 목록.
    # 문자열만 받는다: 사고 층은 MCP도 벤더 스키마도 모른다(Hard Rule #1).
    external_events: list[str] = Field(default_factory=list)
    # 이 세션에서 최근 먼저 건넨 말(🔔). 성찰이 같은 취지를 바꿔 말해 반복하지 않게 보여준다.
    recent_proactive: list[str] = Field(default_factory=list)
    # 성찰 항목마다 코드가 계산한 사실(core 가 채운다). 비어 있으면 decision model 은 원문만 본다
    facts: list[SituationFact] = Field(default_factory=list)
    # 먼저 건넬 말이 인용해야 할 항목. decision gate 가 확률이 가장 높은 항목으로 채운다
    anchor: str = ""
    # 요청 시점이 아닌 백그라운드 성찰(Tier 1 daemon)도 같은 계약을 재사용한다.
    mode: Literal["request", "reflection"] = "request"


def items_to_text(value: Any) -> Any:
    """작은 모델은 문자열 목록 자리에 {"option": "..."} 같은 객체를 넣는다. 결과를 버리는 대신 글자만 건진다."""
    if not isinstance(value, list):
        return value
    return [_item_text(item) for item in value if _item_text(item)]


def _item_text(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return " ".join(str(v).strip() for v in item.values() if isinstance(v, str) and v.strip())
    return str(item).strip()


def when_text(days: int | None, minutes: int | None) -> str:
    """남은 시간을 말로. 시각을 알면 분 단위, 날짜만 알면 날 단위, 둘 다 모르면 "unknown". 순수 함수."""
    if minutes is not None:
        span = abs(minutes)
        if span < 60:
            amount = f"{span}분"
        elif span < 48 * 60:
            hours, rest = divmod(span, 60)
            amount = f"{hours}시간 {rest}분" if rest else f"{hours}시간"
        else:
            amount = f"{span // 1440}일"
        return "지금" if minutes == 0 else f"{amount} {'뒤' if minutes > 0 else '전'}"
    if days is not None:
        return {0: "오늘", 1: "내일", -1: "어제"}.get(days, f"{abs(days)}일 {'뒤' if days > 0 else '전'}")
    return "unknown"
