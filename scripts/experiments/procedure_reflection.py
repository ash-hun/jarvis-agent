"""[scripts] BBEH-mini 반성 학습(EMMA-2)의 held-out 정확도와 수정 종류, 절차 수렴(EMMA-1)의 파일 수를 잰다."""

import os
import sys
import json
import random
import asyncio
import hashlib
import argparse
import tempfile
from typing import Any
from pathlib import Path
from datetime import datetime, timedelta

os.environ.setdefault("JARVIS_LOG_LEVEL", "WARNING")

from scripts.experiments.models import model_config

from jarvis.core.procedures.reflect import Attempt, FailureCase, Reflection, parse_reflection, render_prompt
from jarvis.model_layer.model_types import LLMContext, ModelConfig, StreamOptions, UserMessage
from jarvis.core.procedures.learner import REFERENCE, ProcedureLearner, ReflectionOutcome
from jarvis.memory.memory_service import PATTERN_INJECT_LIMIT, TURN_CHARS, MemoryService
from jarvis.core.procedures.procedures_store import Procedure, ProcedureStore
from jarvis.memory.long_term.task_pattern import best_matches, render_block
from jarvis.core.slash.procedures_cmd import make_procedures_handler
from jarvis.core.skills.skills_registry import SkillRegistry
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.long_term.refine import procedure_source
from jarvis.core.procedures.distill import ProcedureDraft
from jarvis.core.tools.tools_registry import ToolRegistry
from jarvis.model_layer.stream import stream_to_message
from jarvis.core.procedures.update_guard import check
from jarvis.core.procedures.detect import TaskSpan
from jarvis.memory.scope import MemoryScope
import jarvis

RESULTS = Path(__file__).resolve().parent / "results.json"
KEY = "procedure_reflection"
DATA = Path("~/.jarvis/benchmarks/bbeh/bbeh_data.json").expanduser()
CACHE_DIR = Path("~/.jarvis/benchmarks/bbeh/cache").expanduser()
SEED = 42
TRAIN_PER_TASK = 2
HELDOUT_PER_TASK = 8
BACKBONES = ["gpt-4o-mini", "gemma4:e4b", "gemma4:e2b-it-qat"]
EVAL_BACKBONE = "gpt-4o-mini"
SCOPE = MemoryScope(user_id="bench", agent_id="main", session_id="bbeh")
# BBEH 논문이 모든 과제 끝에 붙인 답 형식 지시. 공식 채점기가 이 접두어를 찾는다
SUFFIX = (
    'Think step by step, and when you provide the final answer, please use the prefix "The answer is:" without any'
    " modification, and provide the answer directly, with no formatting, no bolding, and no markup. For instance:"
    ' "The answer is: 42" or "The answer is: yes". If the question is multiple choice with a single correct answer,'
    ' the final answer must only be the letter corresponding to the correct answer. For example, "The answer is: (a)"'
)
SYNTH_SUCCESSES = [0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30]
SYNTH_TASK_TYPES = 40


# ── BBEH 공식 채점(google-deepmind/bbeh evaluate.py 이식) ──


def strip_latex(response: str) -> str:
    if response.startswith("$") and response.endswith("$"):
        response = response[1:-1]
    if "boxed{" in response and response.endswith("}"):
        response = response[0:-1].split("boxed{")[1]
    if "text{" in response and response.endswith("}"):
        response = response[0:-1].split("text{")[1]
    if "texttt{" in response and response.endswith("}"):
        response = response[0:-1].split("texttt{")[1]
    return response


def extract_answer(sample: str) -> str:
    answer = sample
    for prefix in ("The answer is:", "The final answer is ", "The final answer is: ", "The answer is "):
        if prefix in answer:
            answer = answer.split(prefix)[-1].strip()
    if answer.endswith("."):
        answer = answer[:-1]
    return strip_latex(answer)


def fuzzy_match(prediction: str, reference: str) -> bool:
    if prediction == reference:
        return True
    if len(prediction) == 3 and prediction[0] == "(" and prediction[-1] == ")":
        return prediction[1] == reference
    if len(reference) == 3 and reference[0] == "(" and reference[-1] == ")":
        return reference[1] == prediction
    try:
        if float(prediction) == float(reference):
            return True
    except ValueError:
        pass
    if prediction.replace("'", "") == reference.replace("'", ""):
        return True
    if f"[{reference}]" == prediction or f"[{prediction}]" == reference:
        return True
    return prediction.endswith("?") and prediction[:-1] == reference


def preprocess_sample(sample: str) -> str:
    prediction = extract_answer(sample.strip()).lower()
    prediction = prediction.replace(", ", ",").replace("**", "")
    prediction = prediction.split("\n")[0]
    return prediction[0:-1] if prediction.endswith(".") else prediction


def correct(sample: str, reference: str) -> bool:
    return fuzzy_match(preprocess_sample(sample), reference.strip().lower().replace(", ", ","))


# ── 데이터와 LLM 캐시 ──


def split() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """EMMA 처럼 23 범주에서 고르게 나눈다. mini 표시가 있는 460개, 범주마다 seed 고정으로 섞는다."""
    rows = [e for e in json.loads(DATA.read_text(encoding="utf-8")) if str(e.get("mini")) == "1"]
    rng = random.Random(SEED)
    train: list[dict[str, str]] = []
    held: list[dict[str, str]] = []
    for task in sorted({e["task"] for e in rows}):
        items = sorted((e for e in rows if e["task"] == task), key=lambda e: e["input"])
        rng.shuffle(items)
        train += items[:TRAIN_PER_TASK]
        held += items[TRAIN_PER_TASK : TRAIN_PER_TASK + HELDOUT_PER_TASK]
    return train, held


class CachedLLM:
    """같은 (모델, 프롬프트)는 디스크 캐시를 읽는다. 실험을 다시 돌려도 LLM 을 부르지 않는다."""

    def __init__(self, name: str, concurrency: int) -> None:
        self.name = name
        self.config: ModelConfig = model_config(name).model_copy(update={"temperature": 0.0, "timeout": 900.0})
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._path = CACHE_DIR / f"{name.replace(':', '_')}.jsonl"
        self._cache: dict[str, str] = {}
        if self._path.exists():
            for line in self._path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self._cache[row["k"]] = row["v"]
        self._gate = asyncio.Semaphore(concurrency)
        self.calls = 0

    async def __call__(self, prompt: str) -> str:
        key = hashlib.sha1(f"{self.name}\n{prompt}".encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]
        async with self._gate:
            ctx = LLMContext(messages=[UserMessage(content=prompt)], tools=None)
            result = await stream_to_message(self.config, ctx, StreamOptions())
        self.calls += 1
        if result.error_message is not None:
            print(f"[{self.name}] error: {result.error_message[:200]}", file=sys.stderr)
            return ""  # 오류는 캐시하지 않아 다음 실행에서 다시 부른다
        text = result.text()
        self._cache[key] = text
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"k": key, "v": text}, ensure_ascii=False) + "\n")
        return text


def solve_prompt(question: str, memory_block: str) -> str:
    return f"{memory_block}\n\n{question}\n\n{SUFFIX}" if memory_block else f"{question}\n\n{SUFFIX}"


def task_type(task: str) -> str:
    return f"bbeh {task}"


# ── EMMA-2: 반성 학습과 held-out ──


async def learn(llm: CachedLLM, train: list[dict[str, str]], answers: list[str], guard: bool) -> dict[str, Any]:
    """train 을 턴 일화로 쓰고, 실패를 유휴 틱마다 반성하고, 나온 초안을 /procedures approve 로 모두 승인한다."""
    memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
    root = tempfile.mkdtemp(prefix="bbeh_procs_")
    store = ProcedureStore(root)

    async def reflector(case: FailureCase, refusal: str) -> Reflection | None:
        return parse_reflection(await llm(render_prompt(case, refusal)))

    async def no_distill(span: TaskSpan) -> ProcedureDraft | None:
        return None

    learner = ProcedureLearner(store, no_distill, memory=memory, reflector=reflector, guard=guard)
    start = datetime(2026, 11, 1)
    for i, (ex, answer) in enumerate(zip(train, answers, strict=True)):
        ok = correct(answer, ex["target"])
        # 실서비스의 실패 답에는 도구 오류가 담긴다. 여기서는 채점 결과(평가자 요약)를 답 앞에 둔다
        digest = f"[채점] {'정답' if ok else '오답'}. 기대한 답: {ex['target']}, 낸 답: {extract_answer(answer)[:80]}"
        item_id = await memory.record_turn(
            i, ex["input"], f"{digest}\n{answer[-600:]}", SCOPE, task_type=task_type(ex["task"]), failed=not ok,
        )
        item = await memory.get(item_id)
        assert item is not None
        item.occurred_at = start + timedelta(minutes=i)
        item.metadata[REFERENCE] = ex["target"]
        await memory.store.store(item)
    outcomes: list[ReflectionOutcome] = []
    ticks = 0
    while True:
        tick = await learner.reflect(SCOPE)
        if not tick:
            break
        ticks += 1
        outcomes += tick
    handle = make_procedures_handler(store, ToolRegistry(), SkillRegistry(), learner=learner)
    for proc in store.list():
        await handle(f"approve {proc.name}", SCOPE)
    return {"memory": memory, "store": store, "outcomes": outcomes, "ticks": ticks}


def violations(outcomes: list[ReflectionOutcome], train: list[dict[str, str]], answers: list[str]) -> list[str]:
    """거름망 없이 받아들인 제안을 거름망에 다시 넣었을 때 막혔을 이유. 상한은 보지 않는다(room=True)."""
    out: list[str] = []
    for o in outcomes:
        if o.kind not in ("procedure", "task_pattern") or not o.proposals:
            continue
        failed = [
            ex for ex, a in zip(train, answers, strict=True)
            if task_type(ex["task"]) == o.task_type and not correct(a, ex["target"])
        ]
        case = FailureCase(
            SCOPE.agent_id, o.task_type, tuple(Attempt(ex["input"][:TURN_CHARS], "") for ex in failed),
            references=tuple(ex["target"] for ex in failed),
        )
        reason = check(o.proposals[-1], case, room=True)
        if reason:
            out.append(reason)
    return out


def summarize(outcomes: list[ReflectionOutcome]) -> dict[str, Any]:
    kinds = {"procedure": 0, "task_pattern": 0, "no_change": 0, "refused": 0, "blocked": 0}
    proposed: dict[str, int] = {}
    retried = 0
    for o in outcomes:
        kinds[o.kind] = kinds.get(o.kind, 0) + 1
        if o.proposals:
            first = o.proposals[0]
            proposed[f"{first.scope}/{first.action}"] = proposed.get(f"{first.scope}/{first.action}", 0) + 1
        retried += len(o.reasons) > 0
    reasons = [r for o in outcomes for r in o.reasons]
    return {"kinds": kinds, "first_proposals": proposed, "batches": len(outcomes), "retried": retried,
            "reasons": reasons[:40]}


async def context_for(memory: MemoryService, store: ProcedureStore, ex: dict[str, str]) -> str:
    """승인된 절차 중 이 작업 종류의 것과, 질문 낱말에 걸린 작업 패턴(실서비스의 best_matches)을 앞에 둔다.

    실서비스에서 절차는 procedure_<name> 도구로 노출되고 모델이 불러 본문을 받는다.
    도구 없는 실험이라 본문을 바로 넣는다.
    """
    parts: list[str] = []
    source = procedure_source(SCOPE.agent_id, task_type(ex["task"]))
    proc: Procedure | None = next((p for p in store.list() if p.source == source and p.approved), None)
    if proc is not None:
        parts.append(f"[학습된 절차] {proc.description}\n{proc.render('')}")
    patterns = best_matches(await memory.task_patterns(SCOPE), ex["input"], PATTERN_INJECT_LIMIT)
    if patterns:
        parts.append(render_block(patterns))
    return "\n\n".join(parts)


async def evaluate(llm: CachedLLM, held: list[dict[str, str]], learned: dict[str, Any] | None) -> dict[str, Any]:
    blocks = [await context_for(learned["memory"], learned["store"], ex) if learned else "" for ex in held]
    answers = await asyncio.gather(*(llm(solve_prompt(ex["input"], b)) for ex, b in zip(held, blocks, strict=True)))
    hits = [correct(a, ex["target"]) for a, ex in zip(answers, held, strict=True)]
    by_task: dict[str, list[bool]] = {}
    for ex, h in zip(held, hits, strict=True):
        by_task.setdefault(ex["task"], []).append(h)
    return {
        "accuracy": round(sum(hits) / len(hits), 4),
        "correct": sum(hits),
        "n": len(hits),
        "with_memory": sum(bool(b) for b in blocks),
        "by_task": {t: sum(v) for t, v in sorted(by_task.items())},
        "hits": [int(h) for h in hits],
    }


async def emma2(backbones: list[str], eval_backbone: str) -> dict[str, Any]:
    train, held = split()
    out: dict[str, Any] = {"train": len(train), "heldout": len(held), "seed": SEED, "backbones": {}}
    # 실패 궤적은 평가 백본 하나로 고정하고 reflector 백본만 바꾼다. 같은 실패를 보고 어떤 수정을 고르는지가
    # 백본의 습관이다(EMMA Figure 1). 로컬 모델로 BBEH 를 풀면 문항당 몇 분이 걸리는 것도 피한다
    solver = CachedLLM(eval_backbone, concurrency=8)
    answers = list(await asyncio.gather(*(solver(solve_prompt(ex["input"], "")) for ex in train)))
    train_acc = sum(correct(a, ex["target"]) for a, ex in zip(answers, train, strict=True)) / len(train)
    out["solver"] = eval_backbone
    out["train_accuracy"] = round(train_acc, 4)
    for name in backbones:
        llm = solver if name == eval_backbone else CachedLLM(name, concurrency=1)
        row: dict[str, Any] = {}
        learned: dict[str, dict[str, Any]] = {}
        for guard in (False, True):
            arm = "guarded" if guard else "unguarded"
            learned[arm] = await learn(llm, train, answers, guard)
            row[arm] = {**summarize(learned[arm]["outcomes"]), "ticks": learned[arm]["ticks"],
                        "approved": len(learned[arm]["store"].list())}
            if not guard:
                row[arm]["would_refuse"] = violations(learned[arm]["outcomes"], train, answers)
            print(f"[{name}] {arm}: {row[arm]['kinds']}", file=sys.stderr)
        if name == eval_backbone:
            row["heldout"] = {
                "none": await evaluate(llm, held, None),
                "unguarded": await evaluate(llm, held, learned["unguarded"]),
                "guarded": await evaluate(llm, held, learned["guarded"]),
            }
            base = row["heldout"]["none"].pop("hits")
            for arm in ("unguarded", "guarded"):
                hits = row["heldout"][arm].pop("hits")
                # 같은 문항을 짝지어 본다(McNemar). 반성 뒤에만 맞힌 수와 반성 뒤에만 틀린 수
                row["heldout"][arm]["gained"] = sum(h and not b for h, b in zip(hits, base, strict=True))
                row["heldout"][arm]["lost"] = sum(b and not h for h, b in zip(hits, base, strict=True))
            print(f"[{name}] heldout: {({k: v['accuracy'] for k, v in row['heldout'].items()})}", file=sys.stderr)
        row["llm_calls_this_run"] = llm.calls
        out["backbones"][name] = row
    return out


# ── EMMA-1: LLM 없이 절차 파일 수 ──


async def emma1() -> dict[str, Any]:
    """한 작업 종류의 성공이 쌓일 때 파일 수. 세대 방식은 옛 코드의 출처 규칙을 그대로 흉내 낸다.

    첫 초안은 바로 승인한다(사람이 쓰기 시작한 절차). 수렴 방식은 실제 ProcedureLearner.refine 을 돈다.
    """
    draft = ProcedureDraft(name="loan-from-notice", description="공고로 대출 계산", steps=("공고 조회", "대출 계산"))
    calls = {"n": 0}

    async def distill(span: TaskSpan) -> ProcedureDraft | None:
        calls["n"] += 1
        return draft

    scope = MemoryScope(user_id="u1", agent_id="karen", session_id="s1")
    steps = [("lh_notice", {"region": "서울"}), ("housing_loan", {"price": 300_000_000})]
    converged: dict[str, int] = {}
    legacy: dict[str, int] = {}
    migrated: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as root:
        store = ProcedureStore(root)
        memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
        learner = ProcedureLearner(store, distill, memory=memory)
        handle = make_procedures_handler(store, ToolRegistry(), SkillRegistry(), learner=learner)
        done = 0
        for n in SYNTH_SUCCESSES:
            while done < n:
                await memory.record_turn(done, f"서울 공고로 대출 계산 {done}", f"결과 {done}", scope,
                                         task_type="lh_notice", tools=[s for s, _ in steps], steps=steps)
                done += 1
            await learner.refine(scope)
            for p in store.list():
                if not p.approved:
                    await handle(f"approve {p.name}", scope)
            converged[str(n)] = len(store.list())
            legacy[str(n)] = n // 3  # 옛 출처 edm:<에이전트>:<종류>:<세대> 는 세대마다 새 파일이었다
        converge_calls = calls["n"]
    with tempfile.TemporaryDirectory() as root:
        # 옛 세대 파일이 이미 쌓인 디스크: 1세대 승인, 2~10세대 초안
        store = ProcedureStore(root)
        for gen in range(1, 11):
            store.save(Procedure(name=f"loan-from-notice{'' if gen == 1 else f'-{gen}'}", description="d",
                                 body=f"세대 {gen}\n", status="approved" if gen == 1 else "draft",
                                 source=f"edm:karen:lh_notice:{gen}", agent="karen"))
        learner = ProcedureLearner(store, distill)
        before = len(store.list())
        first, second = learner.converge(), learner.converge()
        [kept] = store.list()
        migrated = {
            "files_before": before, "files_after": len(store.list()),
            "archived": len(list((Path(root) / ".archive").glob("*.md"))),
            "groups_first_run": first, "groups_second_run": second,
            "kept_status": kept.status, "revision_generation": kept.revision.generation if kept.revision else None,
        }
    with tempfile.TemporaryDirectory() as root:
        # 작업 종류 40개가 각각 세 번 성공하면 에이전트당 상한에서 멈춘다
        store = ProcedureStore(root)
        memory = MemoryService(InMemoryItemStore(), fixed_facts=0)
        learner = ProcedureLearner(store, distill, memory=memory)
        index = 0
        for t in range(SYNTH_TASK_TYPES):
            for _ in range(3):
                await memory.record_turn(index, f"작업 {t}", f"결과 {index}", scope, task_type=f"tool_{t}",
                                         tools=[f"tool_{t}"], steps=[(f"tool_{t}", {})])
                index += 1
        calls["n"] = 0

        async def distill_named(span: TaskSpan) -> ProcedureDraft | None:
            calls["n"] += 1
            return ProcedureDraft(name=span.steps[0].name.replace("_", "-"), description="d", steps=("a",))

        learner = ProcedureLearner(store, distill_named, memory=memory)
        await learner.refine(scope)
        cap = {"task_types": SYNTH_TASK_TYPES, "files": len(store.list()), "distill_calls": calls["n"]}
    return {
        "successes": SYNTH_SUCCESSES,
        "generational_files": legacy,
        "converged_files": converged,
        "distill_calls_converged": converge_calls,
        "migration": migrated,
        "cap": cap,
    }


def write(result: dict[str, Any]) -> None:
    """다른 에이전트도 같은 파일을 쓴다. 읽고 자기 키만 바꿔 바로 쓴다. 백본을 나눠 돌려도 합친다."""
    data = json.loads(RESULTS.read_text(encoding="utf-8"))
    old = data.get(KEY, {})
    if "emma2" in result and "emma2" in old:
        result["emma2"]["backbones"] = {**old["emma2"].get("backbones", {}), **result["emma2"]["backbones"]}
        result["emma2"] = {**old["emma2"], **result["emma2"]}
    data[KEY] = {**old, **result}
    RESULTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", choices=["emma1", "emma2", "all"], default="all")
    parser.add_argument("--backbones", nargs="*", default=BACKBONES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(f"jarvis from {jarvis.__file__}", file=sys.stderr)
    result: dict[str, Any] = {}
    if args.part in ("emma1", "all"):
        result["emma1"] = asyncio.run(emma1())
    if args.part in ("emma2", "all"):
        if not DATA.exists():
            raise SystemExit(f"BBEH 데이터가 없다: {DATA} (HF BBEH/bbeh 의 bbeh_data.json)")
        result["emma2"] = asyncio.run(emma2(args.backbones, EVAL_BACKBONE))
    print(json.dumps(result, ensure_ascii=False, default=str)[:3000])
    if not args.dry_run:
        write(result)


if __name__ == "__main__":
    main()
