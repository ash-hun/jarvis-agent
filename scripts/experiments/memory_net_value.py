"""[scripts] Memory Tax 의 벤치마크 셋에서 비교군별 정답률과 RAG 대비 benefit, tax 를 재서 results.json 에 쓴다."""

import sys
import json
import random
import asyncio
import argparse
import subprocess
from typing import Any
from pathlib import Path
from scripts.experiments.models import OLLAMA_URL, model_config

from jarvis.memory.eval.benchmark import BenchmarkQuestion, BenchmarkReport, run_benchmark, stratified_sample
from jarvis.memory.eval.eval_cache import CachedEmbedder, JsonlCache, cached_extractor, cached_judge
from jarvis.memory.eval.adapters.personamem import HISTORY_COLUMN, read_rows
from jarvis.memory.consolidation.semantic_extract import llm_fact_extractor
from jarvis.memory.eval.adapters import load_longmemeval, load_personamem
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
) -> BenchmarkReport:
    model = model_config(JUDGE_MODEL).model_copy(update={"temperature": 0.0})
    extractor = cached_extractor(llm_fact_extractor(model), JsonlCache(CACHE / "extract.jsonl"), JUDGE_MODEL)
    judge = cached_judge(llm_judge(model), JsonlCache(CACHE / "judge.jsonl"), JUDGE_MODEL)

    def factory() -> MemoryService:
        return MemoryService(InMemoryItemStore(), extractor=extractor, embedder=embedder, answer_parts=parts)

    report = await run_benchmark(
        name, questions, factory, k=SERVICE_K if service else K, mode=mode, judge=judge, embedder=embedder,
        budget=None if service else BUDGET, warm=embedder.warm, concurrency=CONCURRENCY, fixed=service,
    )
    tag = ".service" if service else ""
    dump = CACHE / "reports" / f"{name}.{mode}.parts{parts}{tag}.json"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return report


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
    args = parser.parse_args()
    names = args.only or list(BENCHMARKS)
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
