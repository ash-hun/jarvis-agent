"""[scripts] KAREN 프롬프트와 청약 도구로 돈 조건 요청을 보내 첫 도구 호출의 현금, 월 상한, 총액 인자를 잰다."""

# uv run python -m scripts.experiments.karen_budget_calls --model gpt-4o-mini --repeat 3
# 도구는 실행하지 않는다. 첫 응답의 도구 이름과 인자만 본다

import yaml
import json
import asyncio
import argparse
from pathlib import Path

from jarvis.core.tools.housing import ProfileStore, housing_tools
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.model_layer.types import LLMContext, UserMessage
from jarvis.core.tools.housing.amount import parse_won
from jarvis.model_layer.stream import stream_to_message
from jarvis.memory.memory_service import MemoryService
from scripts.experiments.models import model_config
from jarvis.model_layer.types import Tool

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "scripts" / "experiments" / "datasets" / "karen_budget.jsonl"
OUT = ROOT / "scripts" / "experiments" / "results.json"
RESULT_KEY = "karen_budget_calls"


def tools() -> list[Tool]:
    store = ProfileStore(MemoryService(InMemoryItemStore()))
    return [
        Tool(name=t.name, description=t.description, parameters=t.parameters) for t in housing_tools(profiles=store)
    ]


def amount(value: object) -> int | None:
    try:
        return parse_won(value) if value not in (None, "") else None
    except ValueError:
        return -1


def judge(case: dict, name: str | None, args: dict) -> list[str]:
    """틀린 점 목록. 비면 맞다."""
    wrong = []
    if name != case["tool"]:
        return [f"도구 {name} (기대 {case['tool']})"]
    for key in ("cash", "monthly_limit", "budget"):
        expected = case.get(key)
        got = amount(args.get(key))
        if expected != got:
            wrong.append(f"{key} {got} (기대 {expected})")
    return wrong


async def run(model: str, repeat: int) -> dict[str, object]:
    system = yaml.safe_load((ROOT / "team" / "karen.yaml").read_text(encoding="utf-8"))["system_prompt"]
    config = model_config(model)
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    for case in cases:
        for _ in range(repeat):
            ctx = LLMContext(messages=[UserMessage(content=case["text"])], tools=tools(), system_prompt=system)
            msg = await stream_to_message(config, ctx)
            call = next(iter(msg.tool_calls()), None)
            name = call.name if call else None
            args = dict(call.arguments) if call else {}
            wrong = judge(case, name, args)
            rows.append({"text": case["text"], "tool": name, "args": args, "wrong": wrong})
            print("OK " if not wrong else "BAD", case["text"][:40], json.dumps(args, ensure_ascii=False), wrong)
    correct = sum(not r["wrong"] for r in rows)
    return {"model": model, "repeat": repeat, "cases": len(cases), "correct": correct, "total": len(rows), "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    result = asyncio.run(run(args.model, args.repeat))
    saved = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    saved[RESULT_KEY] = {k: v for k, v in result.items() if k != "rows"} | {
        "misses": [r for r in result["rows"] if r["wrong"]]  # type: ignore[union-attr]
    }
    OUT.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{result['correct']}/{result['total']} 맞음")


if __name__ == "__main__":
    main()
