"""[memory] 메모리 평가 CLI로, --suite 는 기능별 스위트를, --benchmark 와 --path 는 외부 벤치마크를 돌린다."""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from jarvis.memory.eval.runner import (
    SUITES,
    EvalReport,
    format_report,
    load_retention_suites,
    load_suites,
    load_working_suites,
    merge,
    run,
    run_faithfulness_suite,
    run_retention,
    run_working,
)
from jarvis.memory.eval.target import TARGETS

if TYPE_CHECKING:
    from jarvis.memory.consolidation.semantic_extract import FactExtractor
    from jarvis.memory.consolidation.compaction import Summarizer
    from jarvis.memory.eval.benchmark import Judge, Summarize
    from jarvis.model_layer.types import Message, ModelConfig
    from jarvis.memory.eval.faithfulness import FactJudge
    from jarvis.model_layer.embeddings import Embedder
    from jarvis.memory.scope import MemoryScope


async def _run_all(
    names: list[str], target_name: str, summarizer: str = "extractive", judge: str | None = None
) -> EvalReport:
    reports: list[EvalReport] = []
    target = TARGETS[target_name]()
    store_cases = load_suites(names)
    if store_cases:
        reports.append(await run(store_cases, target))
    retention_cases = load_retention_suites(names)
    if retention_cases:
        reports.append(await run_retention(retention_cases, target))
    working_cases = load_working_suites(names)
    if working_cases:
        reports.append(await run_working(working_cases))
    llm_summarizer_fn: Summarizer | None = None
    llm_judge_fn: FactJudge | None = None
    if summarizer == "llm" or judge == "llm":
        from jarvis.memory.eval.faithfulness import llm_fact_judge
        from jarvis.memory.consolidation import llm_summarizer

        model = _settings_model()
        llm_summarizer_fn = llm_summarizer(model) if summarizer == "llm" else None
        llm_judge_fn = llm_fact_judge(model) if judge == "llm" else None
    faithfulness = await run_faithfulness_suite(names, llm_summarizer_fn, llm_judge_fn)
    if faithfulness is not None:
        reports.append(faithfulness)
    return merge(*reports)


def _settings_model() -> "ModelConfig":
    from jarvis.model_layer.types import ModelConfig
    from jarvis.config import get_settings

    llm = get_settings().llm
    return ModelConfig(
        provider=llm.provider, model=llm.model,
        api_key=llm.api_key.get_secret_value() if llm.api_key else None, base_url=llm.base_url,
    )


async def _run_benchmark(args: argparse.Namespace) -> int:
    from jarvis.memory.eval.benchmark import format_benchmark, run_benchmark, sample
    from jarvis.memory.stores.in_memory import InMemoryItemStore
    from jarvis.memory.memory_service import MemoryService
    from jarvis.memory.eval.adapters import LOADERS

    questions = sample(LOADERS[args.benchmark](Path(args.path)), args.limit, args.seed)

    embedder: Embedder | None
    if args.embedder == "fake":
        from jarvis.memory.eval.fake_embedder import FakeEmbedder

        embedder = FakeEmbedder()
    else:
        from jarvis.model_layer.embeddings import build_embedder
        from jarvis.config import get_settings

        mcfg = get_settings().memory
        key = mcfg.embedding_api_key or get_settings().llm.api_key
        embedder = build_embedder(
            mcfg.embedding_provider, model=mcfg.embedding_model, dimensions=mcfg.embedding_dimensions,
            api_key=key.get_secret_value() if key else None, base_url=mcfg.embedding_base_url,
        )

    model: ModelConfig | None = None
    if args.mode == "full" or args.judge == "llm":
        model = _settings_model()

    save_session: Summarize | None = None
    summarizer: Summarizer | None = None
    extractor: FactExtractor | None = None
    if args.mode == "full":
        from jarvis.memory.consolidation.semantic_extract import llm_fact_extractor
        from jarvis.memory.consolidation.episodic import EpisodicSummarizer
        from jarvis.memory.consolidation import llm_summarizer

        assert model is not None  # mode == "full" 이면 바로 위에서 채웠다
        full_model = model
        summarizer, extractor = llm_summarizer(full_model), llm_fact_extractor(full_model)

    def memory_factory() -> MemoryService:
        return MemoryService(InMemoryItemStore(), summarizer=summarizer, extractor=extractor, embedder=embedder)

    if args.mode == "full":
        async def full_save_session(
            memory: MemoryService, session_id: str, history: "list[Message]", scope: "MemoryScope"
        ) -> str | None:
            return await EpisodicSummarizer(full_model, memory).save_session(session_id, history, scope)

        save_session = full_save_session

    judge: Judge | None = None
    if args.judge == "llm":
        from jarvis.memory.eval.judge import llm_judge

        assert model is not None  # judge == "llm" 이면 위에서 채웠다
        judge = llm_judge(model)
    elif args.judge == "contains":
        from jarvis.memory.eval.judge import contains_judge

        judge = contains_judge()

    report = await run_benchmark(
        args.benchmark, questions, memory_factory, k=args.k, mode=args.mode, save_session=save_session, judge=judge
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) if args.json else format_benchmark(report))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis.memory.eval")
    parser.add_argument("--suite", default="all", choices=("all", *SUITES))
    parser.add_argument("--target", default="store", choices=tuple(TARGETS))
    parser.add_argument("--benchmark", choices=("longmemeval", "locomo"))
    parser.add_argument("--path", help="벤치마크 원본 JSON 경로 (레포 밖, 예: ~/.jarvis/benchmarks/longmemeval_s.json)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", default="raw", choices=("raw", "full"))
    parser.add_argument("--embedder", default="fake", choices=("fake", "config"))
    parser.add_argument("--judge", default=None, choices=("llm", "contains"))
    parser.add_argument("--summarizer", default="extractive", choices=("extractive", "llm"),
                        help="faithfulness 스위트의 요약기. extractive 는 LLM 없는 기준선")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.benchmark:
        if not args.path:
            parser.error("--benchmark needs --path")
        return asyncio.run(_run_benchmark(args))

    names = list(SUITES) if args.suite == "all" else [args.suite]
    report = asyncio.run(_run_all(names, args.target, args.summarizer, args.judge))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report, args.verbose))
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
