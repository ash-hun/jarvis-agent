"""[scripts] Memory Tax 의 벤치마크 셋에서 비교군별 정답률과 RAG 대비 benefit, tax 를 재서 results.json 에 쓴다."""

import sys
import json
import math
import random
import asyncio
import argparse
import subprocess
from typing import Any
from pathlib import Path
from scripts.experiments.models import OLLAMA_URL, model_config

from jarvis.memory.eval.eval_cache import (
    CachedEmbedder, JsonlCache, cached_entity_extractor, cached_extractor, cached_judge,
)
from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkReport, run_benchmark, stratified_sample
from jarvis.memory.eval.adapters.personamem import HISTORY_COLUMN, read_rows
from jarvis.memory.consolidation.semantic_extract import llm_fact_extractor
from jarvis.memory.eval.adapters import load_longmemeval, load_personamem
from jarvis.memory.retrieval.coverage_extract import llm_entity_extractor
from jarvis.memory.memory_service import MAX_TURN_PARTS, MemoryService
from jarvis.memory.eval.adapters.minteval import parse_minteval
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.eval.turn_loss import measure_turn_loss
from jarvis.model_layer.embeddings import OllamaEmbedder
from jarvis.memory.eval.net_value import net_value
from jarvis.memory.eval.judge import llm_judge

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "memory_net_value"
DATA = Path("~/.jarvis/benchmarks").expanduser()
CACHE = DATA / "cache"
SEED = 0
K = 5
# 노출 예산(글자). RAG 조각 k=5 개(조각 최대 1,024자)와 같은 양이다. 비교군마다 k 를 이 예산으로 정한다
BUDGET = 5 * 1024
JUDGE_MODEL = "gpt-4o-mini"
# 기억을 만드는 사실 추출은 답하는 모델과 무관하게 이 모델로 고정한다(모델 비교에서 기억 내용을 같게 둔다)
EXTRACT_MODEL = "gpt-4o-mini"
EMBED_MODEL = "bge-m3"
ARMS = ("rag", "raw", "turns", "turns+src")
# 실서비스 회상(핵심 사실 3건 + 회상 3건, 예산 없음)을 흉내 낸 조건. 출처 회상을 실서비스에서 켤지 이 조건으로 정한다
SERVICE_K = 3
CONCURRENCY = 6
PM_CORPORA = 10
PM_N = 60
LME_N = 60
# MINT-Eval 은 맥락이 길어(대화 영역 중앙값 147만 자) 영역마다 이 글자 수 이하 묶음에서 2개씩, 질문 10개씩 고른다
MINT_CAPS = {"state_tracking": 10_000, "multi_turn_dialogue": 700_000, "wiki_revisions": 250_000,
             "github_commits": 120_000}
MINT_CORPORA = 2
MINT_N = 10
HF = "https://huggingface.co/datasets/bowen-upenn/PersonaMem-v2/resolve/main/"


def longmemeval() -> list[BenchmarkQuestion]:
    return stratified_sample(load_longmemeval(DATA / "longmemeval_s_cleaned.json"), LME_N, SEED)


def personamem() -> list[BenchmarkQuestion]:
    """페르소나(대화 묶음) PM_CORPORA 개를 고르고 그 이력만 받는다. 이미 받은 이력은 다시 받지 않는다."""
    csv_path = DATA / "personamem_v2" / "text" / "benchmark.csv"
    rows = read_rows(csv_path)
    personas = sorted({r["persona_id"] for r in rows}, key=int)
    chosen = set(random.Random(SEED).sample(personas, PM_CORPORA))
    for link in sorted({r[HISTORY_COLUMN] for r in rows if r["persona_id"] in chosen}):
        target = DATA / "personamem_v2" / link
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["curl", "-sfL", "-m", "300", "-o", str(target), HF + link], check=True, timeout=330)
    questions = [q for q in load_personamem(csv_path) if q.corpus.removeprefix("pm") in chosen]
    return stratified_sample(questions, PM_N, SEED)


def minteval() -> list[BenchmarkQuestion]:
    out: list[BenchmarkQuestion] = []
    for split, cap in MINT_CAPS.items():
        records = []
        for line in (DATA / "minteval" / f"{split}.jsonl").read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            rec = json.loads(line)
            if sum(len(c["content"]) for c in rec["contexts"]) <= cap:
                rec["split"] = split
                records.append(rec)
        questions = parse_minteval(records)
        out += stratified_sample(questions, MINT_N, SEED, max_corpora=MINT_CORPORA)
    return out


BENCHMARKS = {"longmemeval_s": longmemeval, "personamem_v2": personamem, "minteval": minteval}


async def run_arm(
    name: str,
    questions: list[BenchmarkQuestion],
    mode: str,
    embedder: CachedEmbedder,
    parts: int = MAX_TURN_PARTS,
    service: bool = False,
    answer_model: str = JUDGE_MODEL,
    judge_model: str = JUDGE_MODEL,
) -> BenchmarkReport:
    extract = model_config(EXTRACT_MODEL).model_copy(update={"temperature": 0.0})
    answer = model_config(answer_model).model_copy(update={"temperature": 0.0})
    grader = model_config(judge_model).model_copy(update={"temperature": 0.0})
    # 예전 캐시(답과 판정 모두 JUDGE_MODEL)는 이름공간을 그대로 둬 다시 사지 않는다
    pair = (answer_model, judge_model)
    namespace = JUDGE_MODEL if pair == (JUDGE_MODEL, JUDGE_MODEL) else f"answer={answer_model}|judge={judge_model}"
    extractor = cached_extractor(llm_fact_extractor(extract), JsonlCache(CACHE / "extract.jsonl"), EXTRACT_MODEL)
    judge = cached_judge(llm_judge(answer, grader), JsonlCache(CACHE / "judge.jsonl"), namespace)

    coverage = cached_entity_extractor(
        llm_entity_extractor(extract), JsonlCache(CACHE / "entities.jsonl"), EXTRACT_MODEL
    ) if mode.startswith("turns+src+cov") else None

    def factory() -> MemoryService:
        return MemoryService(InMemoryItemStore(), extractor=extractor, embedder=embedder, answer_parts=parts,
                             coverage=coverage, coverage_timeout=60.0, timeline=mode.endswith("+tl"))

    report = await run_benchmark(
        name, questions, factory, k=SERVICE_K if service else K, mode=mode, judge=judge, embedder=embedder,
        budget=None if service else BUDGET, warm=embedder.warm, concurrency=CONCURRENCY, fixed=service,
    )
    tag = ".service" if service else ""
    if namespace != JUDGE_MODEL:
        tag += "." + namespace.replace(":", "_").replace("|", ".")
    dump = CACHE / "reports" / f"{name}.{mode}.parts{parts}{tag}.json"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return report


async def service_report(name: str, answer_model: str, judge_model: str) -> BenchmarkReport:
    """실서비스 조건(핵심 사실과 회상, 출처 회상 켬)에서 한 모델의 정답률. 스코어카드 꼭짓점이 부른다."""
    embedder = CachedEmbedder(
        OllamaEmbedder(model=EMBED_MODEL, dimensions=1024, base_url=OLLAMA_URL), CACHE / "embeddings.sqlite"
    )
    try:
        return await run_arm(name, BENCHMARKS[name](), "turns+src", embedder, service=True,
                             answer_model=answer_model, judge_model=judge_model)
    finally:
        embedder.close()


def arm_entry(report: BenchmarkReport) -> dict[str, Any]:
    return {"summary": report.summary(), "by_type": report.by_type()}


async def measure(names: list[str]) -> dict[str, Any]:
    embedder = CachedEmbedder(
        OllamaEmbedder(model=EMBED_MODEL, dimensions=1024, base_url=OLLAMA_URL), CACHE / "embeddings.sqlite"
    )
    out: dict[str, Any] = {}
    try:
        for name in names:
            questions = BENCHMARKS[name]()
            print(f"{name}: 질문 {len(questions)}, 대화 묶음 {len({q.corpus for q in questions})}", file=sys.stderr)
            reports = {}
            for mode in ARMS:
                reports[mode] = await run_arm(name, questions, mode, embedder)
                print(f"  {mode}: {reports[mode].summary()}", file=sys.stderr)
            entry: dict[str, Any] = {
                "n": len(questions),
                "corpora": len({q.corpus for q in questions}),
                "arms": {mode: arm_entry(r) for mode, r in reports.items()},
                "net": {mode: net_value(reports["rag"], r).rates() for mode, r in reports.items() if mode != "rag"},
            }
            if name == "longmemeval_s":
                # MT-3 전후: 조각 일화 없이(이전 코드) 같은 표본을 다시 잰다
                before = await run_arm(name, questions, "turns", embedder, parts=0)
                print(f"  turns(parts 0): {before.summary()}", file=sys.stderr)
                excerpt = await run_arm(name, questions, "turns+excerpt", embedder)
                print(f"  turns+excerpt: {excerpt.summary()}", file=sys.stderr)
                entry["arms"]["turns+excerpt"] = arm_entry(excerpt)
                entry["net"]["turns+excerpt"] = net_value(reports["rag"], excerpt).rates()
                service = {mode: await run_arm(name, questions, mode, embedder, service=True)
                           for mode in ("turns", "turns+src")}
                entry["service"] = {
                    "k": SERVICE_K,
                    "arms": {mode: arm_entry(r) for mode, r in service.items()},
                    "net": {mode: net_value(reports["rag"], r).rates() for mode, r in service.items()},
                    "src_vs_turns": net_value(service["turns"], service["turns+src"]).rates(),
                }
                print(f"  service: {entry['service']['src_vs_turns']}", file=sys.stderr)
                entry["mt3"] = {
                    "turns_before": arm_entry(before),
                    "net_before": net_value(reports["rag"], before).rates(),
                    "turns_after": arm_entry(reports["turns"]),
                }
            out[name] = entry
        print(f"임베딩 실제 호출 {embedder.calls}", file=sys.stderr)
    finally:
        embedder.close()
    return out


def sign_test(benefit: int, tax: int) -> float:
    """이김과 짐만 본 정확 이항 양측 p. 둘 다 0 이면 1."""
    n = benefit + tax
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(benefit, tax) + 1)) / 2**n
    return round(min(1.0, 2 * tail), 4)


def wilson(correct: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = correct / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 4), round(centre + half, 4)]


async def coverage(names: list[str], arms: tuple[str, ...] = ("turns+src", "turns+src+cov")) -> dict[str, Any]:
    """실서비스 조건(k=3, 핵심 사실, 출처 회상)에서 비교군들을 첫 비교군과 맞댄다. 평가 캐시를 그대로 쓴다.

    net 은 마지막 비교군을 첫 비교군과, net_prev 는 바로 앞 비교군과 맞댄 것이다(셋 이상일 때).
    """
    embedder = CachedEmbedder(
        OllamaEmbedder(model=EMBED_MODEL, dimensions=1024, base_url=OLLAMA_URL), CACHE / "embeddings.sqlite"
    )
    out: dict[str, Any] = {}
    try:
        for name in names:
            questions = BENCHMARKS[name]()
            reports = {arm: await run_arm(name, questions, arm, embedder, service=True) for arm in arms}
            nv = net_value(reports[arms[0]], reports[arms[-1]])
            entry: dict[str, Any] = {"n": len(questions), "net": {**nv.rates(), "p": sign_test(nv.benefit, nv.tax)}}
            if len(arms) > 2:
                prev = net_value(reports[arms[-2]], reports[arms[-1]])
                entry["net_prev"] = {**prev.rates(), "p": sign_test(prev.benefit, prev.tax)}
            for label, report in reports.items():
                judged = [r for r in report.results if r.correct is not None]
                right = sum(1 for r in judged if r.correct)
                entry[label] = {**arm_entry(report), "ci95": wilson(right, len(judged))}
            out[name] = entry
            print(f"{name}: {entry['net']}", file=sys.stderr)
    finally:
        embedder.close()
    return out


def turn_loss() -> dict[str, Any]:
    """LongMemEval-s 전체 500문항의 정답 턴. LLM 없이 센다."""
    questions = load_longmemeval(DATA / "longmemeval_s_cleaned.json")
    return {"before": measure_turn_loss(questions, 0).rates(),
            "after": measure_turn_loss(questions, MAX_TURN_PARTS).rates(), "max_parts": MAX_TURN_PARTS}


def write(result: dict[str, Any]) -> None:
    """자기 키만 바꾼다. 다른 실험이 같은 파일을 쓰므로 읽고 바로 쓴다."""
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data.setdefault(KEY, {}).update(result)
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", choices=list(BENCHMARKS), help="이 벤치마크만(기본은 셋 다)")
    parser.add_argument("--dry-run", action="store_true", help="results.json 에 쓰지 않고 출력만")
    parser.add_argument("--coverage", action="store_true", help="실서비스 조건에서 커버리지 재검색 전후만 잰다")
    parser.add_argument("--timeline", action="store_true", help="실서비스 조건에서 커버리지와 타임라인을 더한 전후")
    args = parser.parse_args()
    names = args.only or list(BENCHMARKS)
    if args.coverage or args.timeline:
        key, arms = ("timeline", ("turns+src", "turns+src+cov", "turns+src+cov+tl")) if args.timeline else (
            "coverage", ("turns+src", "turns+src+cov"))
        found = asyncio.run(coverage(names, arms))
        print(json.dumps({n: {"net": e["net"], "net_prev": e.get("net_prev")} for n, e in found.items()},
                         ensure_ascii=False))
        if not args.dry_run:
            write({key: {"config": {"k": SERVICE_K, "judge": JUDGE_MODEL, "extract": EXTRACT_MODEL}, **found}})
        return
    result: dict[str, Any] = {
        "config": {"seed": SEED, "k": K, "budget_chars": BUDGET, "judge": JUDGE_MODEL, "embedder": EMBED_MODEL,
                   "arms": list(ARMS), "max_turn_parts": MAX_TURN_PARTS},
        "turn_loss": turn_loss(),
    }
    benchmarks = asyncio.run(measure(names))
    print(json.dumps({"turn_loss": result["turn_loss"], **benchmarks}, ensure_ascii=False)[:4000])
    if not args.dry_run:
        data = json.loads(RESULTS.read_text(encoding="utf-8")).get(KEY, {})
        result["benchmarks"] = {**data.get("benchmarks", {}), **benchmarks}
        write(result)


if __name__ == "__main__":
    main()
