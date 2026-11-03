"""[scripts] KramaBench 데이터 분석 과제를 낮은 max_turns 로 돌려 넘침 이어가기 전후의 정답률과 완료율을 잰다."""

import os
import re
import sys
import json
import random
import shutil
import signal
import asyncio
import hashlib
import argparse
import tempfile
import contextvars
from typing import Any
from pathlib import Path
from collections.abc import AsyncIterator
from scripts.experiments.models import model_config

from jarvis.model_layer.model_types import (
    AssistantMessage,
    LLMContext,
    ModelConfig,
    StreamEvent,
    StreamOptions,
    TextContent,
    Tool,
    ToolResultMessage,
    UserMessage,
)
from jarvis.agent_layer.agent_types import AgentContext, AgentEndEvent, AgentEvent, AgentLoopConfig
from jarvis.agent_layer.loop_overflow import RESUME_DIRECTIVE, SUMMARY_PROMPT
from jarvis.model_layer.model_registry import get_default_registry
from jarvis.model_layer.providers.provider_base import Provider
from jarvis.core.tools.builtin.read_file import ReadFileTool
from jarvis.core.tools.builtin.list_dir import ListDirTool
from jarvis.agent_layer.loop import run_agent_loop

ROOT = Path.home() / ".jarvis" / "benchmarks" / "kramabench"
CACHE = ROOT / "cache"
RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "loop_overflow"
DOMAINS = ("archeology", "legal")
# 공식 채점에서 LLM 판정(gpt-5-mini paraphrase)이 필요한 유형은 뺀다. 나머지는 코드 채점이라 재현된다
SCORED = {"numeric_exact", "string_exact", "list_exact", "numeric_approximate"}
# 이름: (이어가기, max_turns). None 이면 --max-turns. unbounded 는 과제가 원래 몇 차례를 쓰는지 보는 참고 조건이다
CONDITIONS: dict[str, tuple[bool, int | None]] = {"baseline": (False, None), "resume": (True, None),
                                                   "unbounded": (False, 20)}
PY_TIMEOUT_SEC = 60
OUTPUT_CHARS = 3_000
ANSWER_LINE = re.compile(
    r"^\s*(?:[-•]\s*)?\**\s*(?:ANSWER|지금까지의 답)\s*\**\s*[:：]\s*\**\s*(.+?)\s*\**\s*$", re.M | re.I
)
SYSTEM = (
    "You are a data analyst. The data lake files are in the current working directory. Use list_dir and read_file "
    "to inspect files and the python tool to compute (pandas and openpyxl are installed; print what you need). "
    "Work step by step and verify intermediate values. When you have the result, reply with the final line "
    "`ANSWER: <value>` (a bare number or string; a JSON list if the question asks for several items)."
)
PY_TOOL = Tool(
    name="python",
    description="Run a Python script in the data directory and return stdout/stderr. Print the values you need.",
    parameters={
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python source to run"}},
        "required": ["code"],
    },
)
UV_PYTHON = ["uv", "run", "--no-project", "--quiet", "--with", "pandas", "--with", "openpyxl", "python", "-I"]

# 넘친 풀이만 정리, 이어가기 문구를 본다. 문구가 바뀌면 그 풀이만 다시 풀고, 넘치지 않은 풀이는 캐시를 그대로 쓴다
OVERFLOW_PROMPT = hashlib.sha1((SUMMARY_PROMPT + RESUME_DIRECTIVE).encode()).hexdigest()[:8]

_calls: contextvars.ContextVar[list[int]] = contextvars.ContextVar("loop_overflow_calls")


# ── 과제와 공식 채점(mitdbg/Kramabench benchmark/metrics.py 의 Success, F1, RAEScore 를 옮김) ──

def load_tasks(per_domain: int, seed: int) -> list[dict[str, Any]]:
    """도메인마다 코드로 채점되는 과제에서 seed 로 per_domain 개씩 고른다."""
    picked: list[dict[str, Any]] = []
    for domain in DOMAINS:
        tasks = json.loads((ROOT / "raw" / f"{domain}.json").read_text(encoding="utf-8"))
        pool = sorted((t for t in tasks if t["answer_type"] in SCORED), key=lambda t: t["id"])
        picked += [{**t, "domain": domain} for t in random.Random(seed).sample(pool, min(per_domain, len(pool)))]
    return picked


def _to_number(value: Any) -> Any:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        try:
            return float(cleaned[:-1]) / 100 if cleaned.endswith("%") else float(cleaned)
        except ValueError:
            return value
    return value


def success(predicted: Any, target: Any) -> float:
    if predicted is None:
        return 0.0
    p, t = _to_number(predicted), _to_number(target)
    if isinstance(p, (int, float)) and isinstance(t, (int, float)):
        if p == t:
            return 1.0
        if isinstance(p, float) or isinstance(t, float):
            if t == 0:
                return float(abs(p) < 1e-6)
            diff = abs(p - t)
            return float(diff / abs(t) < 1e-6 or diff < 1e-6 or diff < max(abs(p), abs(t)) * 1e-4)
        return 0.0
    return float(str(predicted).strip().lower() == str(target).strip().lower())


def f1(predicted: Any, target: list[Any]) -> float:
    if isinstance(predicted, str):
        try:
            predicted = json.loads(predicted)
        except json.JSONDecodeError:
            predicted = [s.strip() for s in predicted.split(",") if s.strip()]
    if not isinstance(predicted, list):
        predicted = [predicted]
    if not target:
        return float(not predicted)
    matched: set[int] = set()
    hits = 0
    for t in target:
        for j, p in enumerate(predicted):
            if isinstance(t, str):
                ok = t.strip().lower() == str(p).strip().lower()
            else:
                pp = _to_number(p)
                ok = isinstance(pp, (int, float)) and abs(pp - t) / max(abs(t), 1e-12) < 1e-6
            if ok:
                matched.add(j)
                hits += 1
                break
    recall, precision = hits / len(target), (len(matched) / len(predicted) if predicted else 0.0)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def rae_score(predicted: Any, target: Any) -> float:
    p, t = _to_number(predicted), _to_number(target)
    if not isinstance(p, (int, float)) or not isinstance(t, (int, float)) or t == 0:
        return 0.0
    return 1 / (1 + abs(p - t) / abs(t))


def score(predicted: Any, task: dict[str, Any]) -> float:
    """유형별 공식 대표 지표. exact 는 success, list_exact 는 f1, numeric_approximate 는 rae_score."""
    kind, target = task["answer_type"], task["answer"]
    if kind == "list_exact":
        return f1(predicted, target if isinstance(target, list) else json.loads(target))
    if kind == "numeric_approximate":
        return rae_score(predicted, target)
    return success(predicted, target)


def parse_answer(text: str) -> Any:
    """마지막 ANSWER 줄(또는 정리문의 '지금까지의 답')의 값. 따옴표와 백틱을 벗긴다."""
    found = ANSWER_LINE.findall(text or "")
    if not found:
        return None
    raw = found[-1].strip().strip("`").strip()
    if raw.startswith("["):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw.strip("\"'")


# ── 실행 환경: 데이터 사본 안에서만 도는 도구 ──

def _inside(workdir: Path, raw: str) -> Path | None:
    path = (workdir / raw).resolve()
    return path if path.is_relative_to(workdir) else None


def _result(call_id: str, name: str, text: str, is_error: bool = False) -> ToolResultMessage:
    clipped = text if len(text) <= OUTPUT_CHARS else text[:OUTPUT_CHARS] + f"\n...(잘림, {len(text)}자)"
    return ToolResultMessage(tool_call_id=call_id, tool_name=name, content=[TextContent(text=clipped)],
                             is_error=is_error)


async def run_python(workdir: Path, code: str, cell: int) -> tuple[str, bool]:
    """코드를 사본 디렉터리에 파일로 쓰고 리스트 인자로 실행한다(셸을 거치지 않는다)."""
    script = workdir / f"_cell_{cell}.py"
    script.write_text(code, encoding="utf-8")
    # ponytail: 작업 디렉터리만 사본으로 묶고 파일 시스템 접근은 막지 않는다, 신뢰 못 할 모델을 돌리면 컨테이너 안에서
    proc = await asyncio.create_subprocess_exec(
        *UV_PYTHON, script.name, cwd=workdir, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        # API 키 같은 환경변수는 넘기지 않는다. uv 가 인터프리터와 캐시를 찾을 만큼만
        env={k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "UV_CACHE_DIR", "TMPDIR")},
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), PY_TIMEOUT_SEC)
    except TimeoutError:
        # uv 가 띄운 python 손자 프로세스까지 끝내야 파이프가 닫힌다. uv 만 죽이면 손자가 남아 기다림이 끝나지 않았다
        os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
        return f"timed out after {PY_TIMEOUT_SEC}s", True
    text = out.decode("utf-8", "replace") + (f"\n[stderr]\n{err.decode('utf-8', 'replace')}" if err else "")
    return text or "(no output)", proc.returncode != 0


def make_executor(workdir: Path):  # type: ignore[no-untyped-def]
    read, listing = ReadFileTool(), ListDirTool()
    cells = iter(range(10_000))

    async def execute(call_id: str, name: str, args: dict[str, Any]) -> ToolResultMessage:
        if name == "python":
            text, failed = await run_python(workdir, str(args.get("code", "")), next(cells))
            return _result(call_id, name, text, failed)
        if name in ("read_file", "list_dir"):
            path = _inside(workdir, str(args.get("path", ".")))
            if path is None:
                return _result(call_id, name, "path is outside the data directory", True)
            tool = read if name == "read_file" else listing
            res = await tool.execute(call_id, {**args, "path": str(path)})
            return _result(call_id, name, "\n".join(c.text for c in res.content if isinstance(c, TextContent))
                           .replace(str(workdir) + "/", ""), res.is_error)
        return _result(call_id, name, f"unknown tool {name}", True)

    return execute


class CountingProvider(Provider):
    """실제 provider 를 감싸 이 과제에서 LLM 을 몇 번 불렀는지 센다(정리 호출 포함)."""

    def __init__(self, inner: str) -> None:
        self.provider_name = f"counting-{inner}"
        self._inner = get_default_registry().get(inner)

    def supports_thinking(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    async def stream(
        self, model: ModelConfig, context: LLMContext, options: StreamOptions | None = None
    ) -> AsyncIterator[StreamEvent]:
        _calls.get().append(1)
        async for event in self._inner.stream(model, context, options):
            yield event


def counted(model: str) -> ModelConfig:
    cfg = model_config(model).model_copy(update={"temperature": 0.0})
    get_default_registry().register(CountingProvider(cfg.provider))
    return cfg.model_copy(update={"provider": f"counting-{cfg.provider}"})


# ── 한 과제 ──

def reusable(hit: dict[str, Any]) -> bool:
    """넘치지 않았거나 지금 문구로 넘친 캐시면 다시 쓴다."""
    return not hit.get("overflows") or hit.get("overflow_prompt") == OVERFLOW_PROMPT


def cache_path(model: str, condition: str, task_id: str, max_turns: int) -> Path:
    key = hashlib.sha1(f"{model}|{condition}|{task_id}|{max_turns}|{SYSTEM}".encode()).hexdigest()[:16]
    return CACHE / f"{task_id}_{condition}_{key}.json"


async def run_task(task: dict[str, Any], model: str, condition: str, max_turns: int) -> dict[str, Any]:
    cached = cache_path(model, condition, task["id"], max_turns)
    if cached.exists():
        hit: dict[str, Any] = json.loads(cached.read_text(encoding="utf-8"))
        if reusable(hit):
            return hit
    workdir = Path(tempfile.mkdtemp(prefix=f"krama_{task['id']}_")).resolve()
    shutil.copytree(ROOT / "data" / task["domain"] / "input", workdir, dirs_exist_ok=True)
    _calls.set([])
    ends: list[AgentEndEvent] = []

    async def emit(event: AgentEvent) -> None:
        if isinstance(event, AgentEndEvent):
            ends.append(event)

    context = AgentContext(
        session_id=f"krama-{task['id']}", messages=[UserMessage(content=task["query"])],
        tools=[PY_TOOL, Tool(name="read_file", description=ReadFileTool.description,
                             parameters=ReadFileTool.parameters),
               Tool(name="list_dir", description=ListDirTool.description, parameters=ListDirTool.parameters)],
        model=counted(model), system_prompt=SYSTEM,
    )
    config = AgentLoopConfig(max_turns=max_turns, overflow_resume=CONDITIONS[condition][0],
                             tool_execution_mode="sequential")
    try:
        final = await run_agent_loop(context, config, emit, make_executor(workdir))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    end = ends[-1]
    text = final.text() if isinstance(final, AssistantMessage) else ""
    # 예산을 다 쓴 채 끊긴 기준선은 마지막 답이 도구 호출이다
    cut = isinstance(final, AssistantMessage) and final.stop_reason == "tool_use" and bool(final.tool_calls())
    predicted = parse_answer(text)
    row = {
        "id": task["id"], "domain": task["domain"], "answer_type": task["answer_type"], "condition": condition,
        "turns": end.turns, "overflows": end.overflows, "overflow_prompt": OVERFLOW_PROMPT, "cut_at_budget": cut,
        "llm_calls": len(_calls.get()), "predicted": predicted, "target": task["answer"],
        "score": score(predicted, task), "answer_text": text[-600:],
        "error": final.error_message if isinstance(final, AssistantMessage) else None,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
    return row


def summarize(rows: list[dict[str, Any]], max_turns: int) -> dict[str, Any]:
    n = len(rows)
    overflowed = [r for r in rows if r["overflows"] > 0 or r["cut_at_budget"]]
    completed = [r for r in overflowed if r["overflows"] == 1]
    return {
        "tasks": n,
        "accuracy": round(sum(r["score"] for r in rows) / n, 3),
        "solved": sum(r["score"] >= 0.999 for r in rows),
        "answered": round(sum(r["predicted"] is not None for r in rows) / n, 3),
        "overflow_rate": round(len(overflowed) / n, 3),
        "completed_after_overflow": round(len(completed) / len(overflowed), 3) if overflowed else None,
        "accuracy_overflowed": round(sum(r["score"] for r in overflowed) / len(overflowed), 3) if overflowed else None,
        "mean_llm_calls": round(sum(r["llm_calls"] for r in rows) / n, 2),
        "summary_calls": sum(r["overflows"] for r in rows),
        "max_llm_calls": max(r["llm_calls"] for r in rows),
        "max_turns": max_turns,
        "turns": sorted(r["turns"] for r in rows),
    }


async def run(
    models: list[str], per_domain: int, small: int, max_turns: int, seed: int, concurrency: int
) -> dict[str, Any]:
    tasks = load_tasks(per_domain, seed)
    gate = asyncio.Semaphore(concurrency)
    out: dict[str, Any] = {
        "benchmark": "KramaBench (archeology, legal)", "domains": list(DOMAINS), "seed": seed, "max_turns": max_turns,
        "resume_budget": max(1, max_turns // 2), "scoring": "official: success / f1 / rae_score",
        "models": {},
    }
    for model in models:
        # 첫 모델만 전부, 나머지(로컬 모델)는 도메인마다 앞의 small 개만 돌려 시간을 아낀다
        n = per_domain if model == models[0] else small
        picked = [t for d in DOMAINS for t in [x for x in tasks if x["domain"] == d][:n]]

        async def one(task: dict[str, Any], condition: str, _model: str = model) -> dict[str, Any]:
            async with gate:
                return await run_task(task, _model, condition, CONDITIONS[condition][1] or max_turns)

        by_condition: dict[str, Any] = {}
        for condition in CONDITIONS:
            rows = await asyncio.gather(*(one(t, condition) for t in picked))
            turns = CONDITIONS[condition][1] or max_turns
            by_condition[condition] = {"summary": summarize(list(rows), turns), "rows": [
                {k: r[k] for k in ("id", "turns", "overflows", "llm_calls", "score", "predicted")} for r in rows
            ]}
            print(model, condition, json.dumps(by_condition[condition]["summary"], ensure_ascii=False))
        out["models"][model] = by_condition
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", default=None)
    parser.add_argument("--per-domain", type=int, default=10)
    parser.add_argument("--small", type=int, default=3)
    parser.add_argument("--max-turns", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args()
    if not (ROOT / "raw").exists():
        sys.exit(f"KramaBench 가 없다: {ROOT} (README 의 재현 절차로 받는다)")
    result = asyncio.run(run(args.model or ["gpt-4o-mini"], args.per_domain, args.small, args.max_turns, args.seed,
                             args.concurrency))
    if args.no_save:
        return
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    data[KEY] = result
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
