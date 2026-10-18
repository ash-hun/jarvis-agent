"""[scripts] 요청 사고 한 번이 유효한 프레임을 내는지, 약속(open loop)을 잡아내는지, 얼마나 걸리는지 모델별로 잰다."""

import json
import time
import asyncio
import argparse
import statistics
from pathlib import Path
from scripts.experiments.models import model_config
from scripts.experiments.proactive_situation import engine

from jarvis.agent_layer.thought.types import ThoughtRequest

DATASET = Path(__file__).parent / "datasets" / "thought_requests.jsonl"


async def run(model: str, repeat: int) -> dict[str, object]:
    eng = engine(model)
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    valid = tp = fp = fn = 0
    latencies: list[float] = []
    for _ in range(repeat):
        for case in cases:
            start = time.perf_counter()
            frame = await eng.think(ThoughtRequest(user_input=case["text"], session_id="exp", mode="request"))
            latencies.append(time.perf_counter() - start)
            if frame is None:
                fn += case["expect_loop"]
                continue
            valid += 1
            caught = bool(frame.open_loops)
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
        "latency_p50_s": round(statistics.median(latencies), 2),
        "latency_max_s": round(max(latencies), 2),
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
