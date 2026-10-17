"""[scripts] 컴팩션 요약이 심어 둔 사실을 지키는지, 요약 모델만 바꾸고 판정 모델은 고정해 잰다."""

import argparse
import asyncio
import json

from jarvis.memory.consolidation.compaction import llm_summarizer
from jarvis.memory.eval.faithfulness import (
    contains_fact_judge,
    llm_fact_judge,
    load_faithfulness_cases,
    run_faithfulness_case,
)
from jarvis.memory.eval.runner import DATASETS_DIR
from scripts.experiments.models import model_config

JUDGE = "gpt-4o-mini"


async def run(model: str, repeat: int) -> dict[str, object]:
    cases = load_faithfulness_cases(DATASETS_DIR / "faithfulness.jsonl")
    base = llm_summarizer(model_config(model))
    llm_judge, contains = llm_fact_judge(model_config(JUDGE)), contains_fact_judge()
    kept_llm = kept_contains = total = failed = 0
    samples: list[str] = []
    for _ in range(repeat):
        for case in cases:
            summaries: list[str] = []

            async def summarize(messages, prior, _keep=summaries):  # type: ignore[no-untyped-def]
                text = await base(messages, prior)
                if text:
                    _keep.append(text)
                return text

            result = await run_faithfulness_case(case, summarize, llm_judge)
            if not summaries:
                failed += 1
                continue
            summary = summaries[-1]
            total += len(case.facts)
            kept_llm += len(case.facts) - len(result.missing)
            kept_contains += sum([await contains(summary, f) for f in case.facts])
            if len(samples) < len(cases):
                samples.append(f"[{case.case}] missing(llm)={result.missing} :: {summary[:400]}")
    return {
        "summarizer": model,
        "judge": JUDGE,
        "facts": total,
        "no_summary": failed,
        "retention_llm_judge": round(kept_llm / total, 3) if total else None,
        "retention_contains": round(kept_contains / total, 3) if total else None,
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args()
    for model in args.model:
        print(json.dumps(asyncio.run(run(model, args.repeat)), ensure_ascii=False))


if __name__ == "__main__":
    main()
