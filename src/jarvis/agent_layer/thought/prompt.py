"""[agent_layer] inner thought 프롬프트 템플릿을 파일에서 읽어 플레이스홀더를 채운다."""

from pathlib import Path

# 사용자가 직접 조율하는 지점. 파일이 없으면 이 기본 템플릿을 쓴다.
DEFAULT_TEMPLATE = """\
너는 이 에이전트의 "내적 사고" 모듈이다. 사용자에게 직접 답하지 않는다.
아래 입력을 보고 ThoughtFrame JSON 하나만 출력하라. JSON 외 다른 텍스트는 금지한다.

[말투] {{persona}}
[지금] {{now}}
{{user_model}}
[열린 약속] {{open_loops}}
[회상된 기억] {{recalled_memories}}
[최근 대화] {{history}}
[사용자 입력] {{user_input}}

다음 키를 가진 JSON 객체 하나만 출력하라:
- observation (string): 표면적 사실
- interpretation (string): 진짜 의도, 감정, 말하지 않은 니즈
- recalled (string[]): 활용할 기억 요약
- options (string[]): 가능한 대응들
- proactive_actions (object[]): 지금 먼저 해두면 좋은 행동.
    각 항목: {kind: "suggest"|"tool"|"remember"|"schedule", description, tool_name?, args?, risk: "low"|"high"}
- decision (string): "act" | "ask" | "silent"  (확신 없으면 silent로 기울여라)
- confidence (number): 0.0 ~ 1.0
- rationale (string): 위 결정의 이유
- utterance (string): decision 이 act/ask 일 때 사용자에게 직접 건넬 한두 문장. 사용자를
    분석하는 문장이 아니라 사용자에게 말을 거는 문장으로, [말투]대로 쓴다. silent 면 빈 문자열.
- needs_background (boolean): 답하려면 도구 사용·검색·다단계 작업 등으로 시간이
    걸릴 것 같으면 true. 즉답 가능한 단순 질문이면 false.
- filler (string): needs_background가 true일 때만 채운다. 사용자에게 먼저 건넬
    짧은 즉답으로, [말투]대로 쓰되 반드시 "지금 알아보는 중이라 시간이 조금 걸린다"는 뜻을 자연스럽게
    담아라(예: "잠깐만요, 배포 로그 확인하고 바로 알려드릴게요"). false면 빈 문자열.

원칙: 도움이 안 되면 침묵하라(silent). 저위험 행동만 자율 제안하라.
"""

# daemon 자율 성찰(mode="reflection")용 템플릿: 사용자 요청이 없는 시점.
# 예전 성찰 지시문은 "확신이 없으면 반드시 silent, 애매하면 말하지 마라" 로 침묵을 거듭 밀었다. 정책에도 확신도
# 임계치와 피드백 학습이 있어 침묵이 이중으로 걸렸고, gpt-4o-mini 는 말해야 할 상황의 대부분을 사고 단계에서
# 스스로 침묵으로 정했다(실험 recall 0.17). 사고는 "도움이 되는가" 와 확신도만 정직하게 내고, 거르기는 정책에 맡긴다
DEFAULT_REFLECTION_TEMPLATE = """\
너는 이 에이전트의 "내적 사고" 모듈이다. 지금은 사용자의 직접 요청이 없는 자율 성찰 시점이다.
너의 일은 "지금 먼저 말을 걸면 사용자에게 실제로 도움이 되는가" 를 판단하고, 그 판단을 얼마나 확신하는지
정직하게 적는 것이다. 말을 걸지 최종 결정은 시스템이 확신도와 사용자 피드백으로 한다. 그러니 도움이 된다고
판단하면 스스로 아끼지 말고 act 또는 ask 로 적고, 불확실함은 confidence 로 나타내라.
아래 입력을 보고 ThoughtFrame JSON 하나만 출력하라. JSON 외 다른 텍스트는 금지한다.

[말투] {{persona}}
[지금] {{now}}
{{user_model}}
[열린 약속] {{open_loops}}
[회상된 기억] {{recalled_memories}}
[외부 이벤트] {{external_events}}
[최근에 먼저 건넨 말] {{recent_proactive}}
[최근 대화] {{history}}

판단 기준:
먼저 말할 가치가 있다(하나라도 해당하면 act 또는 ask):
- 열린 약속의 기한이 곧 다가오거나 이미 지났다
- 사용자가 챙기겠다고 한 일의 시각이 되었다
- 외부 이벤트가 사용자의 일이나 일정에 직접 영향을 준다(사용자가 맡은 일의 실패, 변경 요청, 지연, 만료, 자원 부족)
말하지 않는다(silent):
- 기한이 한참 남은 약속이나 막연한 목표
- 이미 끝났거나 사용자가 방금 처리한 일
- 사용자와 관계없는 광고, 뉴스, 단체방 같은 알림
- 대화가 자연스럽게 끝났고 새로 알릴 것이 없다
- 건넬 말이 인사, 안부, "더 궁금한 점 있으면 말씀해 주세요" 뿐이다
- [최근에 먼저 건넨 말]과 같은 취지다. 표현을 바꿔도 다시 말하지 않는다

confidence 는 "지금 말을 거는 것이 도움이 된다" 는 판단의 확신이다:
- 0.9 이상: 기준에 분명히 맞고, 지금 말하지 않으면 사용자가 손해를 본다
- 0.6 ~ 0.9: 기준에 맞지만 사용자가 이미 알고 있을 수도 있다
- 0.6 미만: 기준에 걸치지만 애매하다
silent 로 정했으면 confidence 는 "침묵이 맞다" 는 확신이 아니라 위 판단의 확신이므로 낮게 적는다.

다음 키를 가진 JSON 객체 하나만 출력하라:
- observation (string): 최근 맥락에서 관찰되는 사실
- interpretation (string): 먼저 도울 만한 것 (없으면 빈 문자열)
- recalled (string[]): 근거가 되는 기억 요약
- options (string[]): 가능한 선제 대응들
- proactive_actions (object[]): 지금 먼저 해두면 좋은 행동.
    각 항목: {kind: "suggest"|"tool"|"remember"|"schedule", description, tool_name?, args?, risk: "low"|"high"}
- decision (string): "act" | "ask" | "silent"
- confidence (number): 0.0 ~ 1.0
- rationale (string): 위 결정의 이유. 어느 기준에 해당하는지 적는다
- utterance (string): decision 이 act/ask 일 때 사용자에게 직접 건넬 한두 문장. 사용자를
    분석하는 문장이 아니라 사용자에게 말을 거는 문장으로, [말투]대로 쓴다. silent 면 빈 문자열.
- needs_background (boolean): 성찰에서는 보통 false
- filler (string): 보통 빈 문자열
"""

# 템플릿이 채워야 하는 플레이스홀더 목록(렌더 시 누락 키는 빈 문자열로 치환).
PLACEHOLDERS = (
    "persona",
    "now",
    "open_loops",
    "external_events",
    "recent_proactive",
    "recalled_memories",
    "history",
    "user_input",
    "user_model",
)


class ThoughtPromptTemplate:
    """
    inner thought 프롬프트 템플릿: 로딩 + 렌더를 캡슐화한 독립 객체.

    고도화 여지: few-shot 예시 주입, 모드별(request/reflection) 분기 템플릿,
    토큰 예산에 따른 history 절단 등을 이 클래스 안에서 확장한다.
    """

    def __init__(self, template: str = DEFAULT_TEMPLATE) -> None:
        self._template = template

    @classmethod
    def load(cls, path: str | None, default: str = DEFAULT_TEMPLATE) -> "ThoughtPromptTemplate":
        """경로의 파일을 읽되, 없거나 읽기 실패 시 default 템플릿으로 fallback.

        default를 바꿔 요청용/성찰용 등 용도별 기본 템플릿을 로딩할 수 있다.
        """
        if not path:
            return cls(default)
        p = Path(path).expanduser()
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return cls(default)
        return cls(text.strip() or default)

    def has_placeholder(self, key: str) -> bool:
        """템플릿이 해당 플레이스홀더를 포함하는지. 사용자가 편집한 템플릿에
        새 플레이스홀더가 없을 때 조용한 유실을 막기 위한 판별용."""
        return "{{" + key + "}}" in self._template

    def render(self, **values: str) -> str:
        """플레이스홀더를 치환. 정의되지 않은 키는 빈 문자열로 안전하게 처리."""
        out = self._template
        for key in PLACEHOLDERS:
            out = out.replace("{{" + key + "}}", values.get(key, "") or "")
        return out
