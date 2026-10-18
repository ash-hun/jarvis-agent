"""[scripts] 요청 사고가 유효한 프레임을 내는지, AGENDA 판단이 약속을 잡는지, 각각 얼마나 걸리는지 잰다."""

import json
import time
import asyncio
import argparse
import statistics
from pathlib import Path
from scripts.experiments.models import model_config
from scripts.experiments.proactive_situation import engine

from jarvis.agent_layer.openloop.judge import OpenLoopJudge
from jarvis.agent_layer.thought.types import ThoughtRequest
from jarvis.core.proactive.eval.__main__ import FIXED_CLOCK

DATASET = Path(__file__).parent / "datasets" / "thought_requests.jsonl"


async def run(model: str, repeat: int) -> dict[str, object]:
    eng = engine(model)
    # 약속은 사고가 아니라 매 턴 따로 도는 AGENDA 판단이 잡는다
    judge = OpenLoopJudge(model_config(model), clock=lambda: FIXED_CLOCK)
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    valid = tp = fp = fn = 0
    thought_latencies: list[float] = []
    judge_latencies: list[float] = []
    for _ in range(repeat):
        for case in cases:
            start = time.perf_counter()
            frame = await eng.think(ThoughtRequest(user_input=case["text"], session_id="exp", mode="request"))
            thought_latencies.append(time.perf_counter() - start)
            valid += frame is not None
            start = time.perf_counter()
            verdict = await judge.judge(case["text"], [], [])
            judge_latencies.append(time.perf_counter() - start)
            caught = verdict is not None and bool(verdict.open_loops)
            tp += caught and case["expect_loop"]
            fp += caught and not case["expect_loop"]
            fn += (not caught) and case["expect_loop"]
    n = repeat * len(cases)
    return {
        "model": model,
        "runs": n,
        "valid_frame": round(valid / n, 3),
        "loop_recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "loop_precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "latency_p50_s": round(statistics.median(thought_latencies), 2),
        "latency_max_s": round(max(thought_latencies), 2),
        "judge_latency_p50_s": round(statistics.median(judge_latencies), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--repeat", type=int, default=2)
    args = parser.parse_args()
    for model in args.model:
        model_config(model)
        print(json.dumps(asyncio.run(run(model, args.repeat)), ensure_ascii=False))


if __name__ == "__main__":
    main()
