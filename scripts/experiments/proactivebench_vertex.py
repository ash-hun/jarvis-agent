"""[scripts] ProactiveBench 를 decision model 없는 기본 구성과 모델별 보정 임계치로 돌려 Proactivity 점수를 낸다."""

import json
import time
import httpx
import asyncio
import hashlib
import argparse
import contextvars
from typing import Any
from pathlib import Path
from statistics import mean
from collections import Counter
from scripts.experiments.models import OLLAMA_URL
from scripts.experiments.proactive_decision_first import SWEEP, build, would_speak

from jarvis.core.proactive.eval.proactivebench import (
    BenchEvent,
    scene_events,
    stratified_sample,
    to_thought_request,
    vertex_score,
)
from jarvis.model_layer.model_types import AssistantMessage, LLMContext, ModelConfig, StreamOptions, TextContent, Usage
from jarvis.core.proactive.eval.label_metrics import false_alarm_must_not, recall_must
from jarvis.agent_layer.thought.thought_types import ThoughtFrame
from jarvis.core.proactive.eval.eval_schema import CaseLabel
from jarvis.agent_layer.thought import engine as engine_mod
from jarvis.core.proactive.eval.__main__ import FIXED_CLOCK
from jarvis.model_layer.decision import DecisionModel
from jarvis.jarvis_config import ProactiveConfig

ROOT = Path.home() / ".jarvis" / "benchmarks" / "proactivebench"
DATA = ROOT / "test_data"
CACHE = ROOT / "cache"
SOURCE = "https://raw.githubusercontent.com/thunlp/ProactiveAgent/main/dataset/test_data/"
SPLIT = "real_average"  # splits.json 의 전체 묶음(코딩 6, 글쓰기 6)
MAX_SAMPLE = 100
CONCURRENCY = 8
ITEM_TIMEOUT_SEC = 180.0
DOWNLOAD_TIMEOUT_SEC = 30.0
ITEM_FIELDS = ("id", "label", "spoke", "failed", "confidence", "decision", "error")

_item: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("proactivebench_item")


def ensure_data() -> None:
    """splits.json 과 그 안의 흐름 파일이 없을 때만 받는다. 이미 있으면 아무것도 하지 않는다."""
    DATA.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=DOWNLOAD_TIMEOUT_SEC, follow_redirects=True) as client:
        splits = DATA / "splits.json"
        if not splits.exists():
            _download(client, "splits.json", splits)
        for name in json.loads(splits.read_text(encoding="utf-8"))[SPLIT]["files"]:
            target = DATA / Path(name).name
            if not target.exists():
                _download(client, Path(name).name, target)


def _download(client: httpx.Client, name: str, target: Path) -> None:
    response = client.get(SOURCE + name)
    response.raise_for_status()
    json.loads(response.text)  # JSON 이 아니면 저장하지 않는다
    target.write_text(response.text, encoding="utf-8")


def load_events() -> list[BenchEvent]:
    names = json.loads((DATA / "splits.json").read_text(encoding="utf-8"))[SPLIT]["files"]
    events: list[BenchEvent] = []
    for name in names:
        path = DATA / Path(name).name
        events += scene_events(path.stem, json.loads(path.read_text(encoding="utf-8")))
    return events


def spoke_or_wrong(label: CaseLabel, frame: ThoughtFrame | None, failed: bool, threshold: float) -> bool:
    """실패한 문항은 오답으로 센다. must 는 말하지 않은 것, must_not 은 말한 것으로 본다."""
    if failed:
        return label != "must"
    return would_speak(frame, threshold)


def with_spoke(rows: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    return [{**r, "spoke": spoke_or_wrong(r["label"], r["frame"], r["failed"], threshold)} for r in rows]


def calibrated_threshold(rows: list[dict[str, Any]], fallback: float) -> float:
    """보정 분할에서 recall 빼기 오경보가 가장 큰 임계치. 같으면 높은 쪽(덜 말한다). 두 라벨이 다 없으면 fallback.

    확신도의 눈금은 모델마다 다르다(gpt-4o-mini 는 가장 높아도 0.8). 고정 임계치는 판단력이 아니라 눈금이 맞는지를 잰다.
    """
    labels = [r["label"] for r in rows]
    if not {"must", "must_not"} <= set(labels):
        return fallback
    scored = []
    for t in SWEEP:
        spoke = [r["spoke"] for r in with_spoke(rows, t)]
        scored.append(((recall_must(labels, spoke) or 0.0) - (false_alarm_must_not(labels, spoke) or 0.0), t))
    return max(scored)[1]


def cached_stream() -> Any:
    """같은 (모델, 프롬프트, 스키마)면 디스크 캐시를 읽는다. 오류 응답은 캐시하지 않는다. 문항별 호출과 토큰을 센다."""
    real = engine_mod.stream_to_message

    async def stream(model: ModelConfig, ctx: LLMContext, options: StreamOptions) -> AssistantMessage:
        prompt = ctx.messages[0].content
        raw = json.dumps([model.model, prompt, options.json_schema is not None], ensure_ascii=False, sort_keys=True)
        path = CACHE / f"{hashlib.sha256(raw.encode()).hexdigest()}.json"
        item = _item.get()
        item["llm"] += 1
        if path.exists():
            value = json.loads(path.read_text(encoding="utf-8"))
            item["cached"] += 1
        else:
            message = await real(model, ctx, options)
            value = {"text": message.text(), "usage": {"input": message.usage.input, "output": message.usage.output}}
            if message.error_message or not value["text"]:
                item["error"] = message.error_message or "empty response"
                return message
            CACHE.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        item["input_tokens"] += value["usage"]["input"]
        item["output_tokens"] += value["usage"]["output"]
        usage = Usage(input=value["usage"]["input"], output=value["usage"]["output"])
        return AssistantMessage(content=[TextContent(text=value["text"])], usage=usage)

    return stream


async def run_item(event: BenchEvent, engine: Any, sem: asyncio.Semaphore) -> dict[str, Any]:
    item: dict[str, Any] = {"llm": 0, "cached": 0, "input_tokens": 0, "output_tokens": 0, "error": ""}
    _item.set(item)
    frame: ThoughtFrame | None = None
    async with sem:
        start = time.perf_counter()
        try:
            frame = await asyncio.wait_for(engine.think(to_thought_request(event, FIXED_CLOCK)), ITEM_TIMEOUT_SEC)
        except Exception as exc:  # 한 문항 실패가 전체를 멈추지 않게
            item["error"] = repr(exc)[:200]
        sec = time.perf_counter() - start
    failed = bool(item["error"]) or frame is None
    if frame is None and not item["error"]:
        item["error"] = "no frame (unparsable)"
    return {
        "id": event.id,
        "category": event.category,
        "label": event.label,
        "frame": frame,
        "failed": failed,
        "confidence": frame.confidence if frame else None,
        "decision": frame.decision if frame else "none",
        "utterance": frame.utterance if frame else "",
        "sec": round(sec, 2),
        **item,
    }


def summarize(rows: list[dict[str, Any]], pool: list[BenchEvent], threshold: float) -> dict[str, Any]:
    labels = [r["label"] for r in rows]
    spoke = [r["spoke"] for r in rows]
    recall = recall_must(labels, spoke)
    false_alarm = false_alarm_must_not(labels, spoke)
    fresh = [r for r in rows if r["llm"] > r["cached"]]
    by_category: dict[str, Any] = {}
    for category in sorted({r["category"] for r in rows}):
        mine = [r for r in rows if r["category"] == category]
        ml, ms = [r["label"] for r in mine], [r["spoke"] for r in mine]
        by_category[category] = {
            "n": len(mine), "recall": recall_must(ml, ms), "false_alarm": false_alarm_must_not(ml, ms)
        }
    return {
        "score": vertex_score(recall, false_alarm),
        "n": len(rows),
        "raw": round(vertex_score(recall, false_alarm) / 100, 4),
        "detail": {
            "recall": recall,
            "false_alarm": false_alarm,
            "threshold": threshold,
            "labels": dict(Counter(labels)),
            "pool_labels": dict(Counter(e.label for e in pool)),
            "by_category": by_category,
            "llm_per_item": round(mean(r["llm"] for r in rows), 2) if rows else 0,
            "input_tokens_per_item": round(mean(r["input_tokens"] for r in rows), 1) if rows else 0,
            "output_tokens_per_item": round(mean(r["output_tokens"] for r in rows), 1) if rows else 0,
            "fresh_calls": len(fresh),
            "items": [{k: r[k] for k in ITEM_FIELDS} for r in rows],
        },
        "errors": sum(r["failed"] for r in rows),
    }


async def run_vertex(
    model: str, *, judge_model: str = "gpt-4o", limit: int | None = None, seed: int = 0
) -> dict[str, Any]:
    """judge_model 은 계약을 맞추려 받기만 한다. 사람 라벨로 채점해 판정 LLM 이 필요 없다."""
    ensure_data()
    pool = load_events()
    sample = stratified_sample(pool, min(limit or MAX_SAMPLE, MAX_SAMPLE), seed)
    # 시험 표본에 들지 않은 채점 라벨 사건으로 임계치를 고른다. 시험 표본은 그대로라 전과 같은 문항을 잰다
    picked = {e.id for e in sample}
    calibration = [e for e in pool if e.label in ("must", "must_not") and e.id not in picked]
    fixed = ProactiveConfig().confidence_threshold
    # decision model 없는 기본 구성은 decision 을 부르지 않는다. build 의 자리만 채운다
    engine = build("no_decision", model, DecisionModel("unused", OLLAMA_URL))
    original = engine_mod.stream_to_message
    engine_mod.stream_to_message = cached_stream()  # type: ignore[assignment]
    try:
        sem = asyncio.Semaphore(CONCURRENCY)
        rows = list(await asyncio.gather(*(run_item(e, engine, sem) for e in sample + calibration)))
    finally:
        engine_mod.stream_to_message = original  # type: ignore[assignment]
    test_rows, cal_rows = rows[: len(sample)], rows[len(sample):]
    threshold = calibrated_threshold(cal_rows, fixed)
    out = summarize(with_spoke(test_rows, threshold), pool, threshold)
    at_fixed = summarize(with_spoke(test_rows, fixed), pool, fixed)
    out["detail"]["calibration"] = {
        "n": len(cal_rows), "labels": dict(Counter(r["label"] for r in cal_rows)),
        "failed": sum(r["failed"] for r in cal_rows),
        "rule": "max(recall - false_alarm) over SWEEP on the calibration split, ties to the higher threshold",
    }
    out["detail"]["fixed_threshold"] = {"threshold": fixed, "score": at_fixed["score"],
                                        **{k: at_fixed["detail"][k] for k in ("recall", "false_alarm")}}
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--judge", default="gpt-4o")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    result = asyncio.run(run_vertex(args.model, judge_model=args.judge, limit=args.limit, seed=args.seed))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
