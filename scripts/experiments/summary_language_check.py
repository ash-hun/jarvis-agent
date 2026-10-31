"""[scripts] 요약이 대화 언어를 따르는지 잰다. 한국어, 영어, 코드가 섞인 한국어 대화를 모델마다 요약한다."""

import re
import json
import asyncio
import argparse
from scripts.experiments.models import model_config

from jarvis.model_layer.model_types import AssistantMessage, Message, TextContent, UserMessage
from jarvis.memory.consolidation.compaction import conversation_language, summarize_messages

HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")


def chat(*turns: str) -> list[Message]:
    out: list[Message] = []
    for i, text in enumerate(turns):
        out.append(UserMessage(content=text) if i % 2 == 0 else AssistantMessage(content=[TextContent(text=text)]))
    return out


CONVERSATIONS = {
    "ko_plan": (
        "ko",
        chat(
            "다음 주 화요일에 워크숍 장소를 판교로 바꾸기로 했어",
            "알겠습니다. 판교로 바꿀게요.",
            "예산은 300만원 안에서",
        ),
    ),
    "ko_family": (
        "ko",
        chat("엄마 생신이 토요일이라 케이크 예약해야 해", "어느 가게로 할까요?", "집 앞 베이커리, 3만원대"),
    ),
    "en_launch": (
        "en",
        chat("We moved the launch to March 3rd and the budget is $40k.", "Got it.", "Dana owns the QA sign-off."),
    ),
    "en_bug": (
        "en",
        chat("The login bug only happens on Safari 17.", "Any repro steps?", "Clear cookies, then sign in twice."),
    ),
    "ko_code": (
        "ko",
        chat("pytest 로 tests/unit/test_api.py 돌려줘", "실패 2건이에요.", "test_login 이랑 test_refresh 고쳐야 해"),
    ),
}


def written_in(text: str) -> str:
    return "ko" if len(HANGUL.findall(text)) * 10 >= max(len(LATIN.findall(text)), 1) else "en"


async def run(model: str, repeat: int) -> dict[str, object]:
    rows = []
    for name, (expect, messages) in CONVERSATIONS.items():
        for _ in range(repeat):
            summary = await summarize_messages(model_config(model), messages) or ""
            rows.append(
                {
                    "conversation": name,
                    "expect": expect,
                    "detected": conversation_language(messages),
                    "summary_lang": written_in(summary),
                    "summary": summary[:160],
                }
            )
    ok = sum(r["summary_lang"] == r["expect"] for r in rows)
    return {"model": model, "correct": f"{ok}/{len(rows)}", "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    for model in args.model:
        print(json.dumps(asyncio.run(run(model, args.repeat)), ensure_ascii=False))


if __name__ == "__main__":
    main()
