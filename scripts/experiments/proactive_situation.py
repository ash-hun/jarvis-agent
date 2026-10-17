"""[scripts] 상황 사례로 사고 엔진부터 게이팅까지 돌려, 말해야 할 때 말하고 아닐 때 침묵하는지 모델별로 잰다."""

import argparse
import asyncio
import json
import time

from jarvis.agent_layer.thought import InnerThoughtEngine, ThoughtPromptTemplate
from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE
from jarvis.config import get_settings
from jarvis.core.proactive.eval.__main__ import FIXED_CLOCK
from jarvis.core.proactive.eval.runner import load_suites, run_cases
from scripts.experiments.models import model_config


def engine(model: str) -> InnerThoughtEngine:
    tcfg = get_settings().thought
    return InnerThoughtEngine(
        model=model_config(model),
        template=ThoughtPromptTemplate.load(tcfg.prompt_path),
        reflection_template=ThoughtPromptTemplate.load(
            tcfg.reflection_prompt_path, default=DEFAULT_REFLECTION_TEMPLATE
        ),
        clock=lambda: FIXED_CLOCK,
    )


async def run(model: str, repeat: int) -> dict[str, object]:
    cases = load_suites(["situation"])
    eng = engine(model)
    # 말할지(speak)와 말한 내용에 필요한 낱말이 있는지(mention)를 따로 센다. 하나로 세면 말은 맞게 했는데
    # 낱말 표기가 달라("prod" 와 "프로덕션") 놓친 것으로 잡힌다
    tp = fp = fn = tn = mention_ok = 0
    misses: dict[str, int] = {}
    start = time.perf_counter()
    for _ in range(repeat):
        report = await run_cases(cases, eng)
        for r in report.results:
            if r.expected_speak and r.actual_speak:
                tp += 1
                mention_ok += not r.missing
            elif r.expected_speak:
                fn += 1
                misses[r.case] = misses.get(r.case, 0) + 1
            elif r.actual_speak:
                fp += 1
                misses[r.case] = misses.get(r.case, 0) + 1
            else:
                tn += 1
    calls = repeat * len(cases)
    return {
        "model": model,
        "runs": calls,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "false_alarm": round(fp / (fp + tn), 3) if fp + tn else None,
        "mention_ok_when_spoke": f"{mention_ok}/{tp}",
        "sec_per_case": round((time.perf_counter() - start) / calls, 2),
        "misses": misses,
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
