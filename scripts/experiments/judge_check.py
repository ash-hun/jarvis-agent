"""[scripts] 컴팩션 보존율 판정기를 실제 단서로 만든 정답 예시로 검증한다. 판정 지시문의 예시와는 겹치지 않는다."""

import json
import asyncio
import argparse
from scripts.experiments.models import model_config

from jarvis.memory.eval.faithfulness import llm_fact_judge

KO = (
    "총 예산 1,200만 원 중 설계에 300만 원이 할당되었으며, "
    "회의는 매주 화요일 10시에 다섯 명이 참여하는 것으로 결정되었다."
)
EN = "The user moved to Busan and lives with their dog named Bori. Project deadline on Friday; coffee every morning."
EN2 = (
    "The total budget is 12 million won with 3 million for design. Meetings every Tuesday at 10 AM, five participants."
)
CASES = [
    (KO, "1200만원", True),
    (KO, "화요일", True),
    (KO, "다섯", True),
    (KO, "부산", False),
    (KO, "보리", False),
    (EN, "보리", True),
    (EN, "금요일", True),
    (EN, "커피", True),
    (EN, "부산", True),
    (EN, "화요일", False),
    (EN, "1200만원", False),
    (EN2, "1200만원", True),
    (EN2, "300만원", True),
    (EN2, "화요일", True),
    (EN2, "다섯", True),
    (EN2, "보리", False),
]


async def run(model: str) -> dict[str, object]:
    judge = llm_fact_judge(model_config(model))
    wrong = [(fact, expect) for summary, fact, expect in CASES if await judge(summary, fact) != expect]
    return {"judge": model, "correct": f"{len(CASES) - len(wrong)}/{len(CASES)}", "wrong": wrong}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    for model in parser.parse_args().model:
        print(json.dumps(asyncio.run(run(model)), ensure_ascii=False))


if __name__ == "__main__":
    main()
