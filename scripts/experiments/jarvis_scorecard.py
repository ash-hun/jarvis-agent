"""[scripts] 스코어카드 꼭짓점을 다각형(모델)마다 돌리거나 캐시를 읽어 점수, 구간, 비용을 results.json 에 쓴다."""

import sys
import json
import time
import asyncio
import argparse
from typing import Any
from pathlib import Path
from scripts.experiments.models import CLOUD
from collections.abc import Awaitable, Callable
from scripts.experiments.scorecard_meter import BudgetExhausted, UsageMeter
from scripts.experiments import procedure_reflection, proactive_decision_first
from scripts.experiments.scorecard_points import balanced, cost_usd, fits_budget, estimate_usd, vertex_entry
from scripts.experiments import gaia_bench, tau2_bench, loop_overflow, memory_net_value, proactivebench_vertex

from jarvis.core.proactive.eval.eval_schema import load_cases
from jarvis.agent_layer.agent_types import AgentLoopConfig

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "scorecard_config.json"
RESULTS = HERE / "results.json"
KEY = "scorecard"
STORE = Path("~/.jarvis/benchmarks/scorecard").expanduser()
KRAMA_PER_DOMAIN = 10
KRAMA_CONCURRENCY = 4

Vertex = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


async def memory_vertex(name: str, model: str, cfg: dict[str, Any]) -> dict[str, Any]:
    report = await memory_net_value.service_report(name, model, cfg["judge_model"])
    summary = report.summary()
    accuracy, n = float(summary["accuracy"] or 0.0), int(summary["n"] or 0)
    return vertex_entry(accuracy, n, {"condition": "service turns+src", **summary})


async def custom_scenario(model: str, cfg: dict[str, Any]) -> dict[str, Any]:
    result = await proactive_decision_first.run(
        model, "unused", 3, cfg["judge_model"], ("no_decision",), sheet=False
    )
    test = result["arms"]["no_decision"]["test"]
    labels = [c.effective_label for c in load_cases(proactive_decision_first.SPLITS["test"])]
    n = sum(label in ("must", "must_not") for label in labels)
    detail = {k: test[k] for k in ("threshold", "recall", "false_alarm", "recall_range", "false_alarm_range")}
    return vertex_entry(balanced(test["recall"], test["false_alarm"]), n, {**detail, "repeat": 3})


async def from_contract(
    run: Callable[..., Awaitable[dict[str, Any]]], model: str, cfg: dict[str, Any]
) -> dict[str, Any]:
    out = await run(model, judge_model=cfg["judge_model"], seed=cfg["seed"])
    return vertex_entry(out["raw"], out["n"], {**out.get("detail", {}), "errors": out.get("errors", 0)})


async def kramabench(model: str, cfg: dict[str, Any]) -> dict[str, Any]:
    # 운영 구성 그대로: 기본 max_turns 와 넘침 이어가기
    max_turns = AgentLoopConfig().max_turns
    tasks = loop_overflow.load_tasks(KRAMA_PER_DOMAIN, cfg["seed"])
    gate = asyncio.Semaphore(KRAMA_CONCURRENCY)

    async def one(task: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            return await loop_overflow.run_task(task, model, "resume", max_turns)

    rows = await asyncio.gather(*(one(t) for t in tasks))
    summary = loop_overflow.summarize(list(rows), max_turns)
    return vertex_entry(summary["accuracy"], summary["tasks"], {k: v for k, v in summary.items() if k != "turns"})


async def bbeh(model: str, cfg: dict[str, Any]) -> dict[str, Any]:
    out = await procedure_reflection.emma2([model], model, arms=("guarded",))
    held = out["backbones"][model]["heldout"]
    guarded = held["guarded"]
    return vertex_entry(guarded["accuracy"], guarded["n"], {
        "before_reflection": held["none"]["accuracy"], "gained": guarded["gained"], "lost": guarded["lost"],
    })


VERTICES: dict[str, Vertex] = {
    "personamem_v2": lambda m, c: memory_vertex("personamem_v2", m, c),
    "longmemeval_s": lambda m, c: memory_vertex("longmemeval_s", m, c),
    "minteval": lambda m, c: memory_vertex("minteval", m, c),
    "proactivebench": lambda m, c: from_contract(proactivebench_vertex.run_vertex, m, c),
    "custom_scenario": custom_scenario,
    "tau2": lambda m, c: from_contract(tau2_bench.run_vertex, m, c),
    "gaia": lambda m, c: from_contract(gaia_bench.run_vertex, m, c),
    "kramabench": kramabench,
    "bbeh": bbeh,
}


def load_config() -> dict[str, Any]:
    cfg: dict[str, Any] = json.loads(CONFIG.read_text(encoding="utf-8"))
    # 메모리 실험은 모듈 상수로 기억 생성 모델과 임베딩을 고정한다. 설정과 어긋나면 다른 조건을 재게 된다
    assert cfg["extract_model"] == memory_net_value.EXTRACT_MODEL and cfg["embedder"] == memory_net_value.EMBED_MODEL
    return cfg


def entry_path(polygon: str, vertex: str) -> Path:
    return STORE / polygon / f"{vertex}.json"


def read_entry(polygon: str, vertex: str) -> dict[str, Any] | None:
    path = entry_path(polygon, vertex)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def budget_cost(entry: dict[str, Any], cfg: dict[str, Any]) -> float:
    """이 꼭짓점이 예산 provider 에서 쓴 비용."""
    prices = cfg["prices_per_mtok"]
    return sum(cost_usd(u, prices[m]) for m, u in entry.get("usage", {}).items() if m in prices)


def quote(polygon: dict[str, Any], vertex: dict[str, Any], cfg: dict[str, Any]) -> float | None:
    """기준 다각형의 실측 사용량을 이 다각형의 예산 모델 단가로 옮긴 견적. 기준이 없으면 None."""
    model = polygon[vertex["role"]]
    if CLOUD.get(model) != cfg["budget"]["provider"]:
        return 0.0
    reference = read_entry(cfg["reference_polygon"], vertex["id"])
    if reference is None:
        return None
    ref_poly = next(p for p in cfg["polygons"] if p["id"] == cfg["reference_polygon"])
    usage = reference.get("usage", {}).get(ref_poly[vertex["role"]], {})
    if not usage.get("calls"):
        # 기준 다각형이 예전 실험 캐시로 답해 실측이 없으면 설정의 대략 견적을 쓴다. 그것도 없으면 견적을 못 낸다
        fallback: float | None = cfg["budget"].get("fallback_quotes_usd", {}).get(vertex["id"])
        return fallback
    return estimate_usd(usage, cfg["prices_per_mtok"][model], cfg["budget"]["estimate_margin"])


async def run_polygon(polygon: dict[str, Any], vertex_ids: list[str], cfg: dict[str, Any]) -> None:
    spent = sum(budget_cost(e, cfg) for v in cfg["vertices"] if (e := read_entry(polygon["id"], v["id"])))
    for vertex in [v for v in cfg["vertices"] if v["id"] in vertex_ids]:
        if read_entry(polygon["id"], vertex["id"]) is not None:
            print(f"[{polygon['id']}] {vertex['id']}: 캐시", file=sys.stderr)
            continue
        estimate = quote(polygon, vertex, cfg)
        if estimate is None:
            print(f"[{polygon['id']}] {vertex['id']}: 기준 다각형 실측이 없어 견적을 못 내 건너뛴다", file=sys.stderr)
            continue
        if not fits_budget(spent, estimate, cfg["budget"]["cap_usd"]):
            print(f"[{polygon['id']}] {vertex['id']}: 예산 초과 견적 ${estimate:.2f}(사용 ${spent:.2f}), 건너뛴다",
                  file=sys.stderr)
            continue
        model = polygon[vertex["role"]]
        meter = UsageMeter(cfg["prices_per_mtok"], spent, cfg["budget"]["cap_usd"])
        start = time.perf_counter()
        try:
            with meter.installed():
                entry = await VERTICES[vertex["id"]](model, cfg)
        except BudgetExhausted as exc:
            # 견적보다 많이 썼다. 이 꼭짓점은 기록하지 않고(부분 결과), 남은 꼭짓점도 돌리지 않는다
            print(f"[{polygon['id']}] {vertex['id']}: {exc}, 멈춘다", file=sys.stderr)
            return
        entry.update({"model": model, "usage": meter.usage, "seconds": round(time.perf_counter() - start, 1)})
        entry["budget_usd"] = round(budget_cost(entry, cfg), 3)
        spent += entry["budget_usd"]
        path = entry_path(polygon["id"], vertex["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{polygon['id']}] {vertex['id']}: {entry['score']} (n={entry['n']}, ${entry['budget_usd']})",
              file=sys.stderr)


# 문항별 기록은 꼭짓점 파일(~/.jarvis)에만 둔다. GAIA 처럼 정답을 다시 퍼뜨리면 안 되는 벤치마크가 있고, 크기도 크다
PER_ITEM = ("items", "tasks", "rows")


def public(entry: dict[str, Any]) -> dict[str, Any]:
    return {**entry, "detail": {k: v for k, v in entry["detail"].items() if k not in PER_ITEM}}


def collect(cfg: dict[str, Any]) -> dict[str, Any]:
    polygons = {p["id"]: {v["id"]: public(e) for v in cfg["vertices"] if (e := read_entry(p["id"], v["id"]))}
                for p in cfg["polygons"]}
    return {"config": cfg, "polygons": polygons}


def write(result: dict[str, Any]) -> None:
    """자기 키만 바꾼다. 다른 실험이 같은 파일을 쓰므로 읽고 바로 쓴다."""
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data[KEY] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--polygon", nargs="*", default=[], help="돌릴 다각형 id(기본은 없음, 모으기만)")
    parser.add_argument("--vertex", nargs="*", default=None, help="돌릴 꼭짓점 id(기본은 전부)")
    parser.add_argument("--quote", action="store_true", help="돌리지 않고 꼭짓점별 견적만 출력")
    args = parser.parse_args()
    cfg = load_config()
    vertex_ids = args.vertex or [v["id"] for v in cfg["vertices"]]
    polygons = [p for p in cfg["polygons"] if p["id"] in args.polygon]
    if args.quote:
        for polygon in polygons:
            quotes = {v["id"]: quote(polygon, v, cfg) for v in cfg["vertices"] if v["id"] in vertex_ids}
            known = [q for q in quotes.values() if q is not None]
            print(json.dumps({"polygon": polygon["id"], "quotes": quotes, "total": round(sum(known), 2)}, indent=1))
        return
    for polygon in polygons:
        asyncio.run(run_polygon(polygon, vertex_ids, cfg))
    write(collect(cfg))


if __name__ == "__main__":
    main()
