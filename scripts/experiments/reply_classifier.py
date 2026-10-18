"""[scripts] 짧은 답 분류기(🔔 피드백, 음성 승인)의 정확도, 위험한 허용, 지연을 모델별로 잰다."""

import json
import time
import asyncio
import argparse
import statistics
from pathlib import Path
from scripts.experiments.models import model_config

from jarvis.agent_layer.thought.reply import ReplyClassifier

DATASET = Path(__file__).parent / "datasets" / "reply.jsonl"
ALLOWING = {"allow", "always"}


async def run(model: str, repeat: int) -> dict[str, object]:
    classifier = ReplyClassifier(model_config(model), timeout_sec=60.0)
    cases = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows, latencies = [], []
    for _ in range(repeat):
        for case in cases:
            start = time.perf_counter()
            got = await classifier.classify(case["kind"], case["text"], case["context"], case.get("always", False))
            latencies.append(time.perf_counter() - start)
            rows.append({**case, "got": got})
    out: dict[str, object] = {"model": model, "n": len(rows)}
    for kind in ("feedback", "approval"):
        part = [r for r in rows if r["kind"] == kind]
        out[f"{kind}_accuracy"] = round(sum(r["got"] == r["expect"] for r in part) / len(part), 3)
    approvals = [r for r in rows if r["kind"] == "approval"]
    # 위험한 허용: 허용이 아닌 답을 허용으로 판정. 화면은 unclear 를 거부로 다루므로 그 반대는 안전 쪽 실수다
    out["unsafe_allow"] = sum(r["got"] in ALLOWING and r["expect"] not in ALLOWING for r in approvals)
    # 실제로 쓰이는 결정: 허용(allow, always) 이면 실행, 나머지(deny, unclear)는 거부
    out["approval_decision_accuracy"] = round(
        sum((r["got"] in ALLOWING) == (r["expect"] in ALLOWING) for r in approvals) / len(approvals), 3
    )
    out["missed_allow"] = sum(r["expect"] in ALLOWING and r["got"] not in ALLOWING for r in approvals)
    out["latency_first_s"] = round(latencies[0], 2)
    out["latency_p50_s"] = round(statistics.median(latencies[1:] or latencies), 2)
    misses = [r for r in rows if r["got"] != r["expect"]]
    out["misses"] = [f"{r['kind']}:{r['text']} → {r['got']} (기대 {r['expect']})" for r in misses]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    for model in args.model:
        print(json.dumps(asyncio.run(run(model, args.repeat)), ensure_ascii=False))


if __name__ == "__main__":
    main()
