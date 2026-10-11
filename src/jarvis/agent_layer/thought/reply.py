"""[agent_layer] 🔔 에 대한 짧은 답과 음성 승인 답을 사고 모델로 분류한다(키워드로 판정이 안 될 때만)."""

import asyncio
import json
from typing import Literal

from jarvis.common.logger import get_logger
from jarvis.model_layer.stream import stream_to_message
from jarvis.model_layer.types import LLMContext, ModelConfig, StreamOptions, UserMessage

logger = get_logger(__name__)

ReplyKind = Literal["feedback", "approval"]

FEEDBACK_VERDICTS = ("accept", "dismiss", "other")
APPROVAL_VERDICTS = ("allow", "always", "deny", "unclear")
# 모델이 답을 못 하면 피드백은 보통 메시지로 흘리고, 승인은 거부 쪽(unclear)으로 둔다
FALLBACK = {"feedback": "other", "approval": "unclear"}
# 짧은 분류라 e2b 로 1~2초. 이보다 오래 걸리면 기다리게 하느니 fallback 이 낫다
CLASSIFY_TIMEOUT_SEC = 6.0
TEXT_MAX_CHARS = 200
CONTEXT_MAX_CHARS = 400

FEEDBACK_PROMPT = """\
비서가 사용자에게 먼저 제안을 건넸고, 사용자가 짧게 답했다. 그 답을 분류하라.

[비서의 제안] {context}
[사용자의 답] {text}

- accept: 제안을 받아들이거나 도움이 됐다는 뜻 (예: "응 그걸로 해줘", "오 좋네", "그렇게 해")
- dismiss: 제안이 필요 없거나 거절하거나 미루는 뜻 (예: "지금은 됐어", "그건 신경 쓰지 마", "나중에 볼게")
- other: 제안과 상관없는 새 요청이나 질문, 또는 판단하기 어려운 말

JSON 하나만 출력하라: {{"verdict": "accept" | "dismiss" | "other"}}
"""

APPROVAL_PROMPT = """\
비서가 명령을 실행해도 되는지 물었고, 사용자가 말로 답했다. 그 답을 분류하라.
잘못 허용하면 위험하다. 허용하는 뜻이 분명할 때만 allow 나 always 로 하고, 조금이라도 애매하면 unclear 로 하라.

[실행할 명령] {context}
[항상 허용 선택지] {always_option}
[사용자의 답] {text}

- allow: 이번 한 번 실행하라는 뜻이 분명함 (예: "그거 돌려", "어 실행해 봐", "해도 돼")
- always: 앞으로도 묻지 말고 계속 허용하라는 뜻이 분명함. [항상 허용 선택지]가 없으면 쓰지 마라
- deny: 실행하지 말라는 뜻
- unclear: 위 어느 것인지 분명하지 않음

JSON 하나만 출력하라: {{"verdict": "allow" | "always" | "deny" | "unclear"}}
"""


def build_prompt(kind: ReplyKind, text: str, context: str, has_always: bool = False) -> str:
    """분류 프롬프트. 입력 길이를 잘라 짧은 분류가 긴 프롬프트가 되지 않게 한다."""
    text, context = text.strip()[:TEXT_MAX_CHARS], context.strip()[:CONTEXT_MAX_CHARS]
    if kind == "feedback":
        return FEEDBACK_PROMPT.format(context=context or "(없음)", text=text)
    return APPROVAL_PROMPT.format(
        context=context or "(없음)", always_option="있음" if has_always else "없음", text=text
    )


def verdict_schema(kind: ReplyKind) -> dict[str, object]:
    verdicts = FEEDBACK_VERDICTS if kind == "feedback" else APPROVAL_VERDICTS
    return {
        "type": "object",
        "properties": {"verdict": {"type": "string", "enum": list(verdicts)}},
        "required": ["verdict"],
    }


def parse_verdict(kind: ReplyKind, raw: str, has_always: bool = False) -> str:
    """모델 출력에서 verdict 를 꺼낸다. 모르는 값이면 fallback. 항상 허용 선택지가 없는데 always 면 allow 로 낮춘다."""
    start, end = raw.find("{"), raw.rfind("}")
    verdict = ""
    if start != -1 and end > start:
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            verdict = str(payload.get("verdict", "")).strip().lower()
    allowed = FEEDBACK_VERDICTS if kind == "feedback" else APPROVAL_VERDICTS
    if verdict not in allowed:
        return FALLBACK[kind]
    if verdict == "always" and not has_always:
        return "allow"
    return verdict


class ReplyClassifier:
    """사고 모델에 한 번 묻는 분류기. 실패나 시간 초과는 fallback 으로 돌려 호출부가 늘 답을 받게 한다."""

    def __init__(self, model: ModelConfig, timeout_sec: float = CLASSIFY_TIMEOUT_SEC) -> None:
        self._model = model
        self._timeout_sec = timeout_sec

    async def classify(self, kind: ReplyKind, text: str, context: str = "", has_always: bool = False) -> str:
        if not text.strip():
            return FALLBACK[kind]
        prompt = build_prompt(kind, text, context, has_always)
        try:
            raw = await asyncio.wait_for(self._call_model(prompt, kind), self._timeout_sec)
        except Exception as exc:
            logger.info(f"[Reply] {kind} classify failed: {exc!r}")
            return FALLBACK[kind]
        return parse_verdict(kind, raw, has_always)

    async def _call_model(self, prompt: str, kind: ReplyKind) -> str:
        ctx = LLMContext(messages=[UserMessage(content=prompt)], tools=None)
        msg = await stream_to_message(self._model, ctx, StreamOptions(json_schema=verdict_schema(kind)))
        return msg.text()
