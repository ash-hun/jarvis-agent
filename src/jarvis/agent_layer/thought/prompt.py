from __future__ import annotations

from pathlib import Path

# 사용자가 직접 조율하는 지점. 파일이 없으면 이 기본 템플릿을 쓴다.
DEFAULT_TEMPLATE = """\
너는 Jarvis의 "내적 사고" 모듈이다. 사용자에게 직접 답하지 않는다.
아래 입력을 보고 ThoughtFrame JSON 하나만 출력하라. JSON 외 다른 텍스트는 금지한다.

[지금] {{now}}
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
- needs_background (boolean): 답하려면 도구 사용·검색·다단계 작업 등으로 시간이
    걸릴 것 같으면 true. 즉답 가능한 단순 질문이면 false.
- filler (string): needs_background가 true일 때만 채운다. 사용자에게 먼저 건넬
    짧은 즉답으로, 반드시 "지금 알아보는 중이라 시간이 조금 걸린다"는 뜻을 자연스럽게
    담아라(예: "잠깐만요, 배포 로그 확인하고 바로 알려드릴게요"). false면 빈 문자열.
- open_loops (string[]): 이 입력에서 사용자가 새로 흘린 약속·미완 작업·나중에 챙길
    일을 짧게 적어라(예: "내일 배포 후 결과 공유하기"). 없으면 빈 배열.

원칙: 도움이 안 되면 침묵하라(silent). 저위험 행동만 자율 제안하라.
"""

# daemon 자율 성찰(mode="reflection")용 템플릿 — 사용자 요청이 없는 시점.
# "절제 우선" 원칙을 강하게 걸어 과잉 발화를 막는다.
DEFAULT_REFLECTION_TEMPLATE = """\
너는 Jarvis의 "내적 사고" 모듈이다. 지금은 사용자의 직접 요청이 없는 자율 성찰 시점이다.
최근 맥락을 보고, 사용자에게 먼저 알리거나 도울 가치가 분명할 때만 말하라.
아래 입력을 보고 ThoughtFrame JSON 하나만 출력하라. JSON 외 다른 텍스트는 금지한다.

[지금] {{now}}
[열린 약속] {{open_loops}}
[회상된 기억] {{recalled_memories}}
[최근 대화] {{history}}

다음 키를 가진 JSON 객체 하나만 출력하라:
- observation (string): 최근 맥락에서 관찰되는 사실
- interpretation (string): 먼저 도울 만한 것 (없으면 빈 문자열)
- recalled (string[]): 근거가 되는 기억 요약
- options (string[]): 가능한 선제 대응들
- proactive_actions (object[]): 지금 먼저 해두면 좋은 행동.
    각 항목: {kind: "suggest"|"tool"|"remember"|"schedule", description, tool_name?, args?, risk: "low"|"high"}
- decision (string): "act" | "ask" | "silent"
- confidence (number): 0.0 ~ 1.0
- rationale (string): 위 결정의 이유
- needs_background (boolean): 성찰에서는 보통 false
- filler (string): 보통 빈 문자열
- open_loops (string[]): 보통 빈 배열(성찰은 새 약속을 만들기보다 기존 것을 본다)

[열린 약속]을 보고, 지금 시점에 먼저 상기하거나 처리할 가치가 분명한 항목이
있으면 act/ask로, 없으면 silent로 판단하라.

원칙(중요): 확신이 없으면 반드시 silent로 판단하라. 사용자를 방해할 가치가
분명하지 않으면 침묵이 기본이다. 애매하면 말하지 마라.
"""

# 템플릿이 채워야 하는 플레이스홀더 목록(렌더 시 누락 키는 빈 문자열로 치환).
PLACEHOLDERS = ("now", "open_loops", "recalled_memories", "history", "user_input")


class ThoughtPromptTemplate:
    """
    inner thought 프롬프트 템플릿 — 로딩 + 렌더를 캡슐화한 독립 객체.

    고도화 여지: few-shot 예시 주입, 모드별(request/reflection) 분기 템플릿,
    토큰 예산에 따른 history 절단 등을 이 클래스 안에서 확장한다.
    """

    def __init__(self, template: str = DEFAULT_TEMPLATE) -> None:
        self._template = template

    @classmethod
    def load(cls, path: str | None, default: str = DEFAULT_TEMPLATE) -> ThoughtPromptTemplate:
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

    def render(self, **values: str) -> str:
        """플레이스홀더를 치환. 정의되지 않은 키는 빈 문자열로 안전하게 처리."""
        out = self._template
        for key in PLACEHOLDERS:
            out = out.replace("{{" + key + "}}", values.get(key, "") or "")
        return out
