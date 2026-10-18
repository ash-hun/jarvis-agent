"""[scripts] router 가 요청 턴의 inner thought 여부를 맞게 가르는지 임계별 정확도, 약속 손실, 지연을 잰다."""

import json
import time
import httpx
import argparse
import statistics
from pathlib import Path

from jarvis.agent_layer.thought.router import ROUTE_CRITERIA, ROUTE_INSTRUCTIONS, route_state

DATASET = Path(__file__).parent / "datasets" / "thought_router.jsonl"
DEFAULT_URL = "http://127.0.0.1:11435/v1/systemone"
THRESHOLDS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
DEFAULT_THRESHOLD = 0.3
# ctxN: 직전 N 턴을 넣고 한 번 부른다. max: 맥락 없이(ctx0)와 두 턴(ctx2)으로 두 번 불러 큰 값(jarvis 가 쓰는 방식).
# 맥락을 넣으면 앞 주제를 따라가 화제가 바뀐 요청을 놓치고, 빼면 "응 진행해" 같은 후속 말을 놓친다
POLICIES = ("ctx0", "ctx1", "ctx2", "max")


def p_think(client: httpx.Client, url: str, state: str) -> float:
    body = {
        "model": "router",
        "state": state,
        "questions": {"route": {"type": "choice", "instructions": ROUTE_INSTRUCTIONS, "criteria": ROUTE_CRITERIA}},
    }
    response = client.post(url, json=body)
    response.raise_for_status()
    return float(response.json()["answers"]["route"]["probabilities"]["think"])


def routed_p(client: httpx.Client, url: str, case: dict[str, object], policy: str) -> float:
    request = str(case["request"])
    turns = [(str(user), str(reply)) for user, reply in case.get("turns", [])]  # type: ignore[attr-defined]
    if policy == "max":
        return max(p_think(client, url, route_state(request, turns, n)) for n in (0, 2))
    return p_think(client, url, route_state(request, turns, int(policy.removeprefix("ctx"))))


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 3) if total else None


def score(rows: list[dict[str, object]], threshold: float) -> dict[str, object]:
    """뜻이 갈리는 사례(ambiguous)를 뺀 사례에서 임계 하나의 성적."""
    clear = [r for r in rows if not r.get("ambiguous")]
    think = [r for r in clear if r["expect"] == "think"]
    direct = [r for r in clear if r["expect"] == "direct"]
    promises = [r for r in rows if r.get("expect_loop")]
    return {
        "threshold": threshold,
        "accuracy": _rate(sum((r["p"] >= threshold) == (r["expect"] == "think") for r in clear), len(clear)),
        # 사고가 필요한데 건너뛴 비율의 반대. 놓치면 답의 질이 떨어진다
        "think_recall": _rate(sum(r["p"] >= threshold for r in think), len(think)),
        # 사고가 필요 없는데 건너뛴 비율. 높을수록 사고 호출을 아낀다
        "direct_recall": _rate(sum(r["p"] < threshold for r in direct), len(direct)),
        "think_rate": _rate(sum(r["p"] >= threshold for r in rows), len(rows)),
        # direct 로 가면 사고가 잡던 약속(open loop)을 놓친다
        "promise_loss": _rate(sum(r["p"] < threshold for r in promises), len(promises)),
    }


def run(dataset: Path, url: str, threshold: float, show_text: bool, policy: str) -> dict[str, object]:
    cases = [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows, latencies = [], []
    with httpx.Client(timeout=10.0) as client:
        for case in cases:
            start = time.perf_counter()
            p = routed_p(client, url, case, policy)
            latencies.append(time.perf_counter() - start)
            rows.append({**case, "p": p})
    latencies.sort()
    out: dict[str, object] = {
        "dataset": dataset.name,
        "policy": policy,
        "n": len(rows),
        "ambiguous": sum(bool(r.get("ambiguous")) for r in rows),
        "latency_p50_s": round(statistics.median(latencies), 3),
        "latency_p95_s": round(latencies[int(len(latencies) * 0.95) - 1], 3),
        "sweep": [score(rows, t) for t in THRESHOLDS],
    }
    by_category: dict[str, list[dict[str, object]]] = {}
    for r in rows:
        by_category.setdefault(str(r["category"]), []).append(r)
    out["by_category"] = {
        name: {"n": len(part), **{k: v for k, v in score(part, threshold).items() if k in ("accuracy", "think_rate")}}
        for name, part in sorted(by_category.items())
    }
    misses = [r for r in rows if not r.get("ambiguous") and (r["p"] >= threshold) != (r["expect"] == "think")]
    out["misses"] = [
        f"{r['category']}:{r['request'] if show_text else '-'} p={r['p']:.3f} (기대 {r['expect']})" for r in misses
    ]
    out["ambiguous_cases"] = [
        f"{r['category']}:{r['request'] if show_text else '-'} p={r['p']:.3f} (라벨 {r['expect']})"
        for r in rows
        if r.get("ambiguous")
    ]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--policy", default="ctx2", choices=POLICIES)
    # 실제 대화로 잴 때 원문을 결과에 남기지 않는다
    parser.add_argument("--hide-text", action="store_true")
    args = parser.parse_args()
    result = run(args.dataset, args.url, args.threshold, not args.hide_text, args.policy)
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
