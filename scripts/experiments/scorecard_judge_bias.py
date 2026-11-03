"""[scripts] 기억 꼭짓점의 답을 다른 계열 판정자로 다시 채점해, 판정자 편향이 점수와 순위를 바꾸는지 본다."""

import sys
import json
import asyncio
import argparse
from typing import Any
from scripts.experiments.models import model_config
from scripts.experiments.scorecard_points import compare_verdicts
from scripts.experiments import jarvis_scorecard, memory_net_value
from scripts.experiments.scorecard_meter import BudgetExhausted, UsageMeter

from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamOptions, UserMessage
from jarvis.memory.eval.eval_cache import JsonlCache, cache_key
from jarvis.memory.eval.judge import JUDGE_PROMPT, abstained
from jarvis.memory.eval.benchmark import BenchmarkQuestion
from jarvis.memory.memory_service import MAX_TURN_PARTS
from jarvis.model_layer.stream import stream_to_message

KEY = "scorecard_judge_bias"
# 판정 LLM 을 쓰는 꼭짓점만. PersonaMem-v2 는 객관식이라 코드가 채점하고, 나머지 꼭짓점은 정답 일치나 사람 라벨이다
VERTICES = ("longmemeval_s", "minteval")
# 원래 판정자(gpt-4o)와 다른 계열. 두 계열의 판정이 같은 순위를 내면 판정자가 순위를 만든 것이 아니다
GRADER = "claude-sonnet-5-5"
CACHE = memory_net_value.CACHE / "judge_bias.jsonl"
CONCURRENCY = 4


def report_rows(name: str, answer_model: str, judge_model: str) -> list[dict[str, Any]]:
    """스코어카드 기억 꼭짓점이 남긴 문항별 답과 판정(memory_net_value.run_arm 의 dump)."""
    tag = f".service.answer={answer_model}.judge={judge_model}".replace(":", "_")
    path = memory_net_value.CACHE / "reports" / f"{name}.turns+src.parts{MAX_TURN_PARTS}{tag}.json"
    rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["results"]
    return rows


def llm_judged(row: dict[str, Any], question: BenchmarkQuestion) -> bool:
    """판정 LLM 이 채점한 문항. 객관식과 기권은 코드가 채점해 판정자와 무관하다."""
    return not question.choices and not abstained(row["predicted"] or "")


async def regrade(grader: ModelConfig, question: BenchmarkQuestion, predicted: str, cache: JsonlCache,
                  gate: asyncio.Semaphore) -> bool:
    key = cache_key("judge_bias", GRADER, question.question_id, question.question, question.answer, predicted)
    if key not in cache:
        prompt = JUDGE_PROMPT.format(question=question.question, answer=question.answer or "(없음)",
                                     predicted=predicted)
        async with gate:
            message = await stream_to_message(grader, LLMContext(messages=[UserMessage(content=prompt)], tools=None),
                                              StreamOptions())
        if message.error_message:
            # 판정 실패를 오답으로 캐시하면 편향처럼 보인다. 멈추고 다시 돌린다
            raise RuntimeError(f"판정 실패: {message.error_message}")
        cache.put(key, message.text().strip().lower().startswith("y"))
    return bool(cache.get(key))


async def run(cfg: dict[str, Any]) -> dict[str, Any]:
    grader = model_config(GRADER)
    cache, gate = JsonlCache(CACHE), asyncio.Semaphore(CONCURRENCY)
    out: dict[str, Any] = {"original_judge": cfg["judge_model"], "grader": GRADER, "vertices": {}}
    for name in VERTICES:
        questions = {q.question_id: q for q in memory_net_value.BENCHMARKS[name]()}
        per: dict[str, Any] = {}
        for polygon in cfg["polygons"]:
            rows = report_rows(name, polygon["main"], cfg["judge_model"])
            judged = [i for i, r in enumerate(rows) if llm_judged(r, questions[r["question_id"]])]
            regraded = await asyncio.gather(*(
                regrade(grader, questions[rows[i]["question_id"]], rows[i]["predicted"] or "", cache, gate)
                for i in judged
            ))
            per[polygon["id"]] = compare_verdicts(rows, judged, list(regraded))
        out["vertices"][name] = per
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    cfg = jarvis_scorecard.load_config()
    # 스코어카드와 같은 Anthropic 예산 상한 안에서만 쓴다
    spent = sum(jarvis_scorecard.budget_cost(e, cfg) for p in cfg["polygons"] for v in cfg["vertices"]
                if (e := jarvis_scorecard.read_entry(p["id"], v["id"])))
    meter = UsageMeter(cfg["prices_per_mtok"], spent, cfg["budget"]["cap_usd"])
    try:
        with meter.installed():
            result = asyncio.run(run(cfg))
    except BudgetExhausted as exc:
        sys.exit(f"{exc}, 멈춘다")
    result["budget_usd"] = round(meter.cost(), 3)
    data = json.loads(jarvis_scorecard.RESULTS.read_text(encoding="utf-8"))
    data[KEY] = result
    jarvis_scorecard.RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
