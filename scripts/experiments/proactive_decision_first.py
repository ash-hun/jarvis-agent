"""[scripts] 성찰에서 decision model 을 사고보다 먼저 묻는 구성과 앵커, 사실 계산을 3단 라벨로 비교하고 🔔 누출을 판정한다."""

import csv
import json
import time
import random
import asyncio
import hashlib
import argparse
from typing import Any
from pathlib import Path
from statistics import mean
from types import ModuleType
from datetime import datetime
from collections.abc import Callable, Iterator
from scripts.experiments.models import OLLAMA_URL, model_config
from scripts.experiments.proactive_situation import engine as thought_engine

from jarvis.model_layer.model_types import AssistantMessage, LLMContext, ModelConfig, StreamOptions, TextContent
from jarvis.core.proactive.eval.label_metrics import auc_must, false_alarm_must_not, recall_must
from jarvis.core.proactive.eval.utterance_judge import LABELS, UtteranceJudge, UtteranceVerdict
from jarvis.agent_layer.thought.thought_types import ThoughtFrame, ThoughtRequest
from jarvis.core.proactive.eval.eval_schema import ProactiveCase, load_cases
from jarvis.agent_layer.thought import decision_gate, engine as engine_mod
from jarvis.agent_layer.thought.thought_protocol import ThoughtEngine
from jarvis.core.proactive.eval.runner import DATASETS_DIR, run_cases
from jarvis.core.proactive.eval.__main__ import FIXED_CLOCK
from jarvis.core.proactive.eval import utterance_judge
from jarvis.model_layer.decision import DecisionModel
from jarvis.model_layer import stream as stream_mod

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "proactive_decision_first"
DATASETS = Path(__file__).resolve().parent / "datasets"
SPLITS = {"dev": DATASETS_DIR / "situation.jsonl", "test": DATASETS / "situation_test.jsonl"}
CACHE = Path("~/.jarvis/benchmarks/proactive_gate/cache.json").expanduser()
PROACTIVEBENCH = Path("~/.jarvis/benchmarks/proactivebench/rm_test.jsonl").expanduser()
JUDGE_SHEET = DATASETS / "utterance_label_review.csv"
ARMS = ("think_first", "decision_first", "anchor", "anchor_facts")
ARM_NAMES = {
    "think_first": "현재(사고 뒤 decision)",
    "decision_first": "판정 먼저",
    "anchor": "판정 먼저 + 앵커",
    "anchor_facts": "판정 먼저 + 앵커 + 사실과 Boolean",
}
SWEEP = (0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9)
SEED = 42
SHEET_SIZE = 30


class Cache:
    """(반복 번호, 모델, 입력) 마다 답과 걸린 시간을 남긴다. 다시 돌리면 호출 없이 같은 값과 같은 시간을 낸다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.rep = 0
        self.calls = {"llm": 0, "decision": 0}
        self.seconds = 0.0

    def key(self, *parts: Any) -> str:
        raw = json.dumps([self.rep, *parts], ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()

    async def get(self, kind: str, key: str, call: Callable[[], Any]) -> Any:
        self.calls[kind] += 1
        if key not in self.data:
            start = time.perf_counter()
            value = await call()
            self.data[key] = {"value": value, "sec": time.perf_counter() - start}
        self.seconds += self.data[key]["sec"]
        return self.data[key]["value"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")


class CachedDecision(DecisionModel):
    def __init__(self, model: str, cache: Cache) -> None:
        super().__init__(model, OLLAMA_URL)
        self._cache = cache

    async def _ask(self, state: str | dict[str, Any], question: dict[str, Any]) -> dict[str, Any] | None:
        key = self._cache.key("decision", self.model, state, question)
        answer: dict[str, Any] | None = await self._cache.get("decision", key, lambda: super(CachedDecision, self)._ask(state, question))
        return answer


def cached_stream(cache: Cache) -> Callable[..., Any]:
    real = stream_mod.stream_to_message

    async def stream(model: ModelConfig, ctx: LLMContext, options: StreamOptions) -> AssistantMessage:
        prompt = ctx.messages[0].content
        key = cache.key("llm", model.model, prompt, options.json_schema is not None)

        async def call() -> dict[str, Any]:
            message = await real(model, ctx, options)
            return {"text": message.text(), "error": message.error_message}

        value = await cache.get("llm", key, call)
        return AssistantMessage(content=[TextContent(text=value["text"])] if value["text"] else [], error_message=value["error"])

    return stream


def swap(module: ModuleType, name: str, value: Any) -> Any:
    """모듈 이름을 바꾸고 원래 값을 돌려준다(캐시와 호출 수 세기를 LLM 경계에 끼운다)."""
    previous = getattr(module, name)
    setattr(module, name, value)
    return previous


class ThinkFirst(ThoughtEngine):
    """바꾸기 전 순서: 사고를 먼저 돌리고 decision model 확률로 결정과 확신도를 바꾼다(비교 기준)."""

    def __init__(self, inner: ThoughtEngine, decision: DecisionModel, gate: decision_gate.DecisionGatedEngine) -> None:
        self._inner = inner
        self._decision = decision
        self._gate = gate

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        frame = await self._inner.think(request)
        if frame is None:
            return None
        state = decision_gate.decision_state(request, FIXED_CLOCK)
        p = await self._decision.yes_probability(
            state, decision_gate.SPEAK_QUESTION, decision_gate.SPEAK_NO, decision_gate.SPEAK_YES
        )
        if p is None:
            return frame
        speak = p >= decision_gate.UTTERANCE_FLOOR
        utterance = frame.utterance if speak else ""
        if speak and not utterance.strip():
            utterance = await self._gate._utterance(state, "")
        decision = (frame.decision if frame.decision in ("act", "ask") else "act") if speak and utterance else "silent"
        return frame.model_copy(update={"decision": decision, "confidence": p, "utterance": utterance})


class Recorder(ThoughtEngine):
    def __init__(self, inner: ThoughtEngine) -> None:
        self.inner = inner
        self.frames: list[ThoughtFrame | None] = []

    async def think(self, request: ThoughtRequest) -> ThoughtFrame | None:
        frame = await self.inner.think(request)
        self.frames.append(frame)
        return frame


def build(arm: str, model: str, decision: DecisionModel) -> ThoughtEngine:
    inner = thought_engine(model)
    utterance_model = model_config(model)
    if arm == "think_first":
        helper = decision_gate.DecisionGatedEngine(inner, decision, utterance_model, clock=lambda: FIXED_CLOCK)
        return ThinkFirst(inner, decision, helper)
    return decision_gate.DecisionGatedEngine(
        inner,
        decision,
        utterance_model,
        clock=lambda: FIXED_CLOCK,
        anchor=arm in ("anchor", "anchor_facts"),
        facts=arm == "anchor_facts",
    )


def would_speak(frame: ThoughtFrame | None, threshold: float) -> bool:
    return bool(frame and frame.decision in ("act", "ask") and frame.confidence >= threshold and frame.utterance.strip())


async def run_split(arm: str, cases: list[ProactiveCase], model: str, decision_name: str, cache: Cache, repeat: int) -> list[dict[str, Any]]:
    """반복마다 사례별 라벨, 확신도, 건넨 말, 호출 수, 시간을 남긴다."""
    rows: list[dict[str, Any]] = []
    for rep in range(repeat):
        cache.rep = rep
        recorder = Recorder(build(arm, model, CachedDecision(decision_name, cache)))
        for case in cases:
            before = dict(cache.calls), cache.seconds
            report = await run_cases([case], recorder, facts_now=FIXED_CLOCK)
            frame = recorder.frames[-1]
            history = case.situation.history if case.situation else []
            rows.append(
                {
                    "rep": rep,
                    "case": case.case,
                    "label": case.effective_label,
                    "confidence": report.results[0].confidence,
                    "utterance": frame.utterance if frame else "",
                    "decision": frame.decision if frame else "none",
                    "anchor_missing": bool(frame and "anchor missing" in frame.rationale),
                    "last_answer": next((t.text for t in reversed(history) if t.role == "assistant"), ""),
                    "llm": cache.calls["llm"] - before[0]["llm"],
                    "decision_calls": cache.calls["decision"] - before[0]["decision"],
                    "sec": cache.seconds - before[1],
                    "frame": frame,
                }
            )
        cache.save()
    return rows


def metrics(rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """반복별 recall, 오경보, AUC 의 평균과 최소 최대, 사례당 호출과 시간."""
    reps = sorted({r["rep"] for r in rows})
    per: dict[str, list[float]] = {"recall": [], "false_alarm": [], "auc": []}
    for rep in reps:
        mine = [r for r in rows if r["rep"] == rep]
        labels = [r["label"] for r in mine]
        spoke = [would_speak(r["frame"], threshold) for r in mine]
        for name, value in (
            ("recall", recall_must(labels, spoke)),
            ("false_alarm", false_alarm_must_not(labels, spoke)),
            ("auc", auc_must(labels, [r["confidence"] for r in mine])),
        ):
            if value is not None:
                per[name].append(value)
    out: dict[str, Any] = {"threshold": threshold}
    for name, values in per.items():
        out[name] = round(mean(values), 3)
        out[f"{name}_range"] = [round(min(values), 3), round(max(values), 3)]
    out["llm_per_case"] = round(mean(r["llm"] for r in rows), 2)
    out["decision_per_case"] = round(mean(r["decision_calls"] for r in rows), 2)
    out["sec_per_case"] = round(mean(r["sec"] for r in rows), 2)
    out["anchor_missing"] = sum(r["anchor_missing"] for r in rows)
    return out


def pick_threshold(rows: list[dict[str, Any]]) -> float:
    """개발용에서 recall 빼기 오경보가 가장 큰 임계치. 같으면 높은 쪽(덜 말한다)."""
    scored = [(m["recall"] - m["false_alarm"], t) for t in SWEEP for m in [metrics(rows, t)]]
    return max(scored)[1]


async def judge_all(items: list[tuple[str, str]], cache: Cache, model: str) -> list[UtteranceVerdict | None]:
    judge = UtteranceJudge(model_config(model))
    cache.rep = 0
    out: list[UtteranceVerdict | None] = []
    for utterance, last in items:
        key = cache.key("judge", model, utterance, last)
        value = await cache.get("llm", key, lambda: _judge_dump(judge, utterance, last))
        out.append(UtteranceVerdict.model_validate(value) if value else None)
    cache.save()
    return out


async def _judge_dump(judge: UtteranceJudge, utterance: str, last: str) -> dict[str, Any] | None:
    verdict = await judge.judge(utterance, last)
    return verdict.model_dump() if verdict else None


def distribution(verdicts: list[UtteranceVerdict | None]) -> dict[str, int]:
    counts: dict[str, int] = {label: 0 for label in LABELS}
    counts["none"] = 0
    for v in verdicts:
        counts[v.label if v else "none"] += 1
    return counts


async def proactivebench_leniency(cache: Cache, model: str) -> dict[str, Any] | None:
    """ProactiveBench reward test 의 제안 과제(사람이 수락 30, 거절 30)를 같은 판정자에 넣는다. 라벨 뜻이 달라 관대함 보조 점검으로만 본다."""
    if not PROACTIVEBENCH.exists():
        return None
    rows = [json.loads(line) for line in PROACTIVEBENCH.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if r.get("pred_task")]
    verdicts = await judge_all([(str(r["pred_task"]), "") for r in rows], cache, model)
    out: dict[str, Any] = {"n": len(rows)}
    for category in sorted({r["category"] for r in rows}):
        picked = [v for r, v in zip(rows, verdicts, strict=True) if r["category"] == category]
        out[category] = {"n": len(picked), "concrete_notice": round(sum(bool(v and v.label == "concrete_notice") for v in picked) / len(picked), 3)}
    return out


def write_sheet(items: list[dict[str, Any]]) -> None:
    """사람 검수 시트. 판정자 라벨과 구성 이름은 넣지 않는다(블라인드). 이미 사람 라벨이 있으면 덮지 않는다."""
    if JUDGE_SHEET.exists():
        return
    with JUDGE_SHEET.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "utterance", "last_answer", "human_label", "human_evidence"])
        for item in items:
            writer.writerow([item["id"], item["utterance"], item["last_answer"], "", ""])


def human_agreement(lookup: dict[str, str]) -> dict[str, Any]:
    """시트에 사람 라벨이 있으면 판정자와 라벨별 일치율. 없으면 검증 전."""
    if not JUDGE_SHEET.exists():
        return {"status": "검증 전", "labeled": 0}
    with JUDGE_SHEET.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["human_label"].strip() in LABELS]
    if len(rows) < 20:
        return {"status": "검증 전", "labeled": len(rows)}
    human = [r["human_label"].strip() for r in rows]
    judged = [lookup.get(r["id"]) for r in rows]
    agree = utterance_judge.agreement_by_label(human, judged)  # type: ignore[arg-type]
    return {"status": "검증됨", "labeled": len(rows), "agreement": {k: round(v, 3) for k, v in agree.items()}}


def spoken_rows(rows: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for r in rows:
        if r["utterance"].strip() and r["decision"] in ("act", "ask"):
            yield r


async def run(
    model: str, decision_name: str, repeat: int, judge_model: str, arms: tuple[str, ...], sheet: bool = True
) -> dict[str, Any]:
    cache = Cache(CACHE)
    llm_modules = (engine_mod, decision_gate, utterance_judge)
    original = [swap(module, "stream_to_message", cached_stream(cache)) for module in llm_modules]
    blocked: list[dict[str, Any]] = []
    real_anchor: Callable[[str, str], bool] = getattr(decision_gate, "anchor_present")

    def watch_anchor(anchor: str, utterance: str) -> bool:
        ok = real_anchor(anchor, utterance)
        if not ok:
            blocked.append({"anchor": anchor, "utterance": utterance})
        return ok

    swap(decision_gate, "anchor_present", watch_anchor)
    try:
        cases = {split: load_cases(path) for split, path in SPLITS.items()}
        result: dict[str, Any] = {"model": model, "decision": decision_name, "repeat": repeat, "arms": {}}
        spoken_items: list[dict[str, Any]] = []
        for arm in arms:
            dev = await run_split(arm, cases["dev"], model, decision_name, cache, repeat)
            threshold = pick_threshold(dev)
            test = await run_split(arm, cases["test"], model, decision_name, cache, repeat)
            spoken = [r for r in spoken_rows(test) if would_speak(r["frame"], threshold)]
            spoken_items += [{"arm": arm, **r} for r in spoken]
            result["arms"][arm] = {
                "name": ARM_NAMES[arm],
                "dev": metrics(dev, threshold),
                "test": metrics(test, threshold),
                "test_sweep": {str(t): {k: v for k, v in metrics(test, t).items() if k in ("recall", "false_alarm")} for t in SWEEP},
                "test_misses": _misses(test, threshold),
            }
        verdicts = await judge_all([(r["utterance"], r["last_answer"]) for r in spoken_items], cache, judge_model)
        blocked_verdicts = await judge_all([(b["utterance"], "") for b in blocked], cache, judge_model)
        for arm in arms:
            mine = [v for r, v in zip(spoken_items, verdicts, strict=True) if r["arm"] == arm]
            result["arms"][arm]["leak_labels"] = distribution(mine)
        result["anchor_blocked"] = {"n": len(blocked), "labels": distribution(blocked_verdicts), "examples": [b["utterance"][:80] for b in blocked[:5]]}
        ids = {f"u{i:03d}": r for i, r in enumerate(spoken_items)}
        lookup = {i: (v.label if v else "") for i, v in zip(ids, verdicts, strict=True)}
        rng = random.Random(SEED)
        unique = list({r["utterance"]: (i, r) for i, r in ids.items()}.values())
        sample = rng.sample(unique, min(SHEET_SIZE, len(unique)))
        if sheet:
            write_sheet([{"id": i, "utterance": r["utterance"], "last_answer": r["last_answer"]} for i, r in sorted(sample)])
        result["judge"] = {"model": judge_model, "human": human_agreement(lookup), "proactivebench": await proactivebench_leniency(cache, judge_model)}
        cache.save()
        return result
    finally:
        for module, previous in zip(llm_modules, original, strict=True):
            swap(module, "stream_to_message", previous)
        swap(decision_gate, "anchor_present", real_anchor)


def _misses(rows: list[dict[str, Any]], threshold: float) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        spoke = would_speak(r["frame"], threshold)
        if (r["label"] == "must" and not spoke) or (r["label"] == "must_not" and spoke):
            out[r["case"]] = out.get(r["case"], 0) + 1
    return out


async def leniency_only(judge_model: str) -> dict[str, Any] | None:
    cache = Cache(CACHE)
    original = swap(utterance_judge, "stream_to_message", cached_stream(cache))
    try:
        return await proactivebench_leniency(cache, judge_model)
    finally:
        swap(utterance_judge, "stream_to_message", original)


def save(result: dict[str, Any]) -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data[KEY] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--decision", default="tev1")
    parser.add_argument("--judge", default="gpt-4o-mini")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--arms", nargs="*", default=list(ARMS))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--leniency-only", action="store_true", help="Ollama 없이 ProactiveBench 관대함 점검만")
    args = parser.parse_args()
    if args.leniency_only:
        print(json.dumps(asyncio.run(leniency_only(args.judge)), ensure_ascii=False))
        return
    result = asyncio.run(
        run(args.model, args.decision, args.repeat, args.judge, tuple(args.arms), sheet=not args.dry_run)
    )
    print(json.dumps({arm: {"test": v["test"], "leak": v["leak_labels"]} for arm, v in result["arms"].items()}, ensure_ascii=False, indent=1))
    print(json.dumps(result["judge"], ensure_ascii=False))
    if not args.dry_run:
        save(result)


if __name__ == "__main__":
    main()
