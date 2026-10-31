"""[scripts] 상황 사례로 사고 엔진부터 게이팅까지 돌려, 말해야 할 때 말하고 아닐 때 침묵하는지 모델별로 잰다."""

import json
import time
import asyncio
import argparse
from pathlib import Path
from scripts.experiments.models import OLLAMA_URL, model_config

from jarvis.agent_layer.thought import InnerThoughtEngine, ThoughtEngine, ThoughtPromptTemplate
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.agent_layer.thought.prompt import DEFAULT_REFLECTION_TEMPLATE
from jarvis.agent_layer.thought.decision_gate import DecisionGatedEngine
from jarvis.core.proactive.eval.runner import load_suites, run_cases
from jarvis.core.proactive.eval.eval_schema import load_cases
from jarvis.core.proactive.eval.__main__ import FIXED_CLOCK
from jarvis.model_layer.decision import DecisionModel
from jarvis.jarvis_config import get_settings

SWEEP = (0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9)


class Recorder(ThoughtEngine):
    """안쪽 엔진의 프레임을 남긴다. 정책과 같은 규칙(결정, 확신도, 건넬 말)으로 임계치별 결과를 다시 계산하려고."""

    def __init__(self, inner: ThoughtEngine) -> None:
        self.inner = inner
        self.frames: list[ThoughtFrame | None] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        frame = await self.inner.think(request)
        self.frames.append(frame)
        return frame


def would_speak(frame: ThoughtFrame | None, threshold: float) -> bool:
    return bool(
        frame and frame.decision in ("act", "ask") and frame.confidence >= threshold and frame.utterance.strip()
    )


def sweep(frames: list[ThoughtFrame | None], expected: list[bool]) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for t in SWEEP:
        spoke = [would_speak(f, t) for f in frames]
        tp = sum(s and e for s, e in zip(spoke, expected, strict=True))
        fp = sum(s and not e for s, e in zip(spoke, expected, strict=True))
        pos, neg = sum(expected), len(expected) - sum(expected)
        out[str(t)] = {
            "recall": round(tp / pos, 3) if pos else None,
            "false_alarm": round(fp / neg, 3) if neg else None,
        }
    return out


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


async def run(model: str, repeat: int, cases_path: str = "", decision: str = "") -> dict[str, object]:
    # 기본은 개발용 상황 사례. --cases 로 지시문 작업 중에 보지 않은 hold-out 사례를 따로 잰다
    cases = load_cases(Path(cases_path)) if cases_path else load_suites(["situation"])
    eng = engine(model)
    if decision:
        # 성찰의 결정과 확신도를 decision model 확률로 바꾼다(제품의 JARVIS_PROACTIVE__DECISION_MODEL 과 같은 래퍼)
        eng = DecisionGatedEngine(
            eng, DecisionModel(decision, OLLAMA_URL), model_config(model), clock=lambda: FIXED_CLOCK, floor=0.0
        )
    # 말할지(speak)와 말한 내용에 필요한 낱말이 있는지(mention)를 따로 센다. 하나로 세면 말은 맞게 했는데
    # 낱말 표기가 달라("prod" 와 "프로덕션") 놓친 것으로 잡힌다
    eng = recorder = Recorder(eng)
    expected: list[bool] = []
    tp = fp = fn = tn = mention_ok = 0
    misses: dict[str, int] = {}
    silent_by: dict[str, int] = {}
    start = time.perf_counter()
    for _ in range(repeat):
        report = await run_cases(cases, eng)
        expected += [c.expect.speak for c in cases]
        for r in report.results:
            if r.expected_speak and r.actual_speak:
                tp += 1
                mention_ok += not r.missing
            elif r.expected_speak:
                fn += 1
                misses[r.case] = misses.get(r.case, 0) + 1
                # 놓친 이유: 사고가 스스로 침묵(decision=silent)인가, 임계치나 쿨다운에 걸렸나
                why = r.reason.split(" ")[0]
                silent_by[why] = silent_by.get(why, 0) + 1
            elif r.actual_speak:
                fp += 1
                misses[r.case] = misses.get(r.case, 0) + 1
            else:
                tn += 1
    calls = repeat * len(cases)
    return {
        "model": model,
        "decision": decision or None,
        "runs": calls,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "false_alarm": round(fp / (fp + tn), 3) if fp + tn else None,
        "mention_ok_when_spoke": f"{mention_ok}/{tp}",
        "sec_per_case": round((time.perf_counter() - start) / calls, 2),
        "misses": misses,
        "missed_because": silent_by,
        # 정책 임계치 0.6 외의 임계치에서의 결과. 같은 프레임으로 다시 계산한다
        "threshold_sweep": sweep(recorder.frames, expected),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--cases", default="")
    parser.add_argument("--decision", default="")
    args = parser.parse_args()
    for model in args.model:
        print(json.dumps(asyncio.run(run(model, args.repeat, args.cases, args.decision)), ensure_ascii=False))


if __name__ == "__main__":
    main()
