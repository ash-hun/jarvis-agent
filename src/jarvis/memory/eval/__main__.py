"""python -m jarvis.memory.eval --suite all|...|working|faithfulness [--summarizer extractive|llm] [--judge llm]
python -m jarvis.memory.eval --benchmark longmemeval|locomo --path FILE [--limit N] [--k 5] [--mode raw|full]
                             [--embedder fake|config] [--judge llm|contains]
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from jarvis.memory.eval.runner import (
    SUITES,
    EvalReport,
    format_report,
    load_suites,
    load_working_suites,
    merge,
    run,
    run_faithfulness_suite,
    run_working,
)
from jarvis.memory.eval.target import TARGETS


async def _run_all(
    names: list[str], target_name: str, summarizer: str = "extractive", judge: str | None = None
) -> EvalReport:
    reports = []
    store_cases = load_suites(names)
    if store_cases:
        reports.append(await run(store_cases, TARGETS[target_name]()))
    working_cases = load_working_suites(names)
    if working_cases:
        reports.append(await run_working(working_cases))
    llm_summarizer_fn = llm_judge_fn = None
    if summarizer == "llm" or judge == "llm":
        from jarvis.memory.consolidation import llm_summarizer
        from jarvis.memory.eval.faithfulness import llm_fact_judge

        model = _settings_model()
        llm_summarizer_fn = llm_summarizer(model) if summarizer == "llm" else None
        llm_judge_fn = llm_fact_judge(model) if judge == "llm" else None
    faithfulness = await run_faithfulness_suite(names, llm_summarizer_fn, llm_judge_fn)
    if faithfulness is not None:
        reports.append(faithfulness)
    return merge(*reports)


def _settings_model():
    from jarvis.config import get_settings
    from jarvis.model_layer.types import ModelConfig

    llm = get_settings().llm
    return ModelConfig(
        provider=llm.provider, model=llm.model,
        api_key=llm.api_key.get_secret_value() if llm.api_key else None, base_url=llm.base_url,
    )


async def _run_benchmark(args: argparse.Namespace) -> int:
    from jarvis.memory.eval.adapters import LOADERS
    from jarvis.memory.eval.benchmark import format_benchmark, run_benchmark, sample
    from jarvis.memory.manager import MemoryManager
    from jarvis.memory.stores.in_memory import InMemoryItemStore

    questions = sample(LOADERS[args.benchmark](Path(args.path)), args.limit, args.seed)

    if args.embedder == "fake":
        from jarvis.memory.eval.fake_embedder import FakeEmbedder

        embedder = FakeEmbedder()
    else:
        from jarvis.config import get_settings
        from jarvis.model_layer.embeddings import build_embedder

        mcfg = get_settings().memory
        key = mcfg.embedding_api_key or get_settings().llm.api_key
        embedder = build_embedder(
            mcfg.embedding_provider, model=mcfg.embedding_model, dimensions=mcfg.embedding_dimensions,
            api_key=key.get_secret_value() if key else None, base_url=mcfg.embedding_base_url,
        )

    model = None
    if args.mode == "full" or args.judge == "llm":
        from jarvis.config import get_settings
        from jarvis.model_layer.types import ModelConfig

        llm = get_settings().llm
        model = ModelConfig(
            provider=llm.provider, model=llm.model,
            api_key=llm.api_key.get_secret_value() if llm.api_key else None, base_url=llm.base_url,
        )

    save_session = None
    summarizer = None
    extractor = None
    if args.mode == "full":
        from jarvis.memory.consolidation import llm_summarizer
        from jarvis.memory.consolidation.episodic import EpisodicSummarizer
        from jarvis.memory.consolidation.semantic_extract import llm_fact_extractor

        summarizer, extractor = llm_summarizer(model), llm_fact_extractor(model)

    def memory_factory() -> MemoryManager:
        return MemoryManager(InMemoryItemStore(), summarizer=summarizer, extractor=extractor, embedder=embedder)

    if args.mode == "full":
        async def save_session(session_id, history, scope):  # noqa: F811
            return await EpisodicSummarizer(model, memory_factory()).save_session(session_id, history, scope)

    judge = None
    if args.judge == "llm":
        from jarvis.memory.eval.judge import llm_judge

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
