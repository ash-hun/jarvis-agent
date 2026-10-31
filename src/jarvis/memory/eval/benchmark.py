"""[memory] 외부 벤치마크의 긴 다중 세션 대화를 메모리에 넣고 질문으로 회상해 증거 재현율을 잰다."""

import random
from typing import Any
from datetime import datetime
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field

from jarvis.memory.memory_service import MemoryService
from jarvis.memory.memory_types import MemoryItem
from jarvis.memory.scope import MemoryScope

USER = "benchmark"

# mode raw: 턴마다 일화 하나, LLM 없이 검색 품질만 본다(기본, 빠름).
# mode turns: 하네스처럼 사용자 발화와 답을 턴 일화(EDM) 하나로 쓰고 세션 끝에 공고화. 추출기를 주면 LLM 이 돈다.
# 증거 재현율은 LLM 없이 계산하고, 정답 포함 여부(accuracy)는 --judge 일 때만 LLM 으로 판정한다.


@dataclass
class BenchmarkTurn:
    role: str  # user | assistant
    text: str
    turn_id: str
    is_evidence: bool = False


@dataclass
class BenchmarkSession:
    session_id: str
    date: str
    turns: list[BenchmarkTurn]


@dataclass
class BenchmarkQuestion:
    question_id: str
    question_type: str
    question: str
    answer: str
    sessions: list[BenchmarkSession]
    evidence_session_ids: set[str] = field(default_factory=set)
    evidence_turn_ids: set[str] = field(default_factory=set)


@dataclass
class QuestionResult:
    question_id: str
    question_type: str
    retrieved: list[str]  # 상위 K 항목 내용
    session_hit: bool  # 상위 K 에 증거 세션의 항목이 있는가
    turn_hit: bool | None  # 턴 단위 증거가 있는 벤치마크만
    correct: bool | None = None  # --judge 일 때만
    predicted: str | None = None


@dataclass
class BenchmarkReport:
    name: str
    mode: str
    k: int
    results: list[QuestionResult]

    def by_type(self) -> dict[str, dict[str, float | int | None]]:
        groups: dict[str, list[QuestionResult]] = {}
        for r in self.results:
            groups.setdefault(r.question_type, []).append(r)
        out: dict[str, dict[str, float | int | None]] = {}
        for qtype, rs in sorted(groups.items()):
            judged = [r for r in rs if r.correct is not None]
            with_turn = [r for r in rs if r.turn_hit is not None]
            out[qtype] = {
                "n": len(rs),
                "session_recall": sum(r.session_hit for r in rs) / len(rs),
                "turn_recall": sum(bool(r.turn_hit) for r in with_turn) / len(with_turn) if with_turn else None,
                "accuracy": sum(bool(r.correct) for r in judged) / len(judged) if judged else None,
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "mode": self.mode, "k": self.k, "by_type": self.by_type(),
                "results": [asdict(r) for r in self.results]}


def sample(questions: list[BenchmarkQuestion], limit: int | None, seed: int = 0) -> list[BenchmarkQuestion]:
    if limit is None or limit >= len(questions):
        return questions
    rng = random.Random(seed)
    return rng.sample(questions, limit)


# ── 메모리에 넣기 ──────────────────────────────────────────────────────────────


async def ingest_raw(memory: MemoryService, question: BenchmarkQuestion) -> None:
    """턴마다 일화 하나. 세션과 턴 id 를 태그로 남겨 증거 재현율을 계산한다."""
    for session in question.sessions:
        scope = MemoryScope(user_id=USER, agent_id="main", session_id=session.session_id)
        created = _parse_date(session.date)
        for turn in session.turns:
            await memory.remember(
                f"[{turn.role}] {turn.text}",
                source="benchmark",
                scope=scope,
                tags=[f"session:{session.session_id}", f"turn:{turn.turn_id}"],
                created_at=created,
            )


async def ingest_turns(memory: MemoryService, question: BenchmarkQuestion) -> None:
    """사용자 발화와 바로 뒤의 답을 턴 일화 하나로. 두 턴 id 를 태그로 남겨 증거 재현율을 계산한다."""
    for session in question.sessions:
        scope = MemoryScope(user_id=USER, agent_id="main", session_id=session.session_id)
        created = _parse_date(session.date)
        index = 0
        pending: tuple[str, str] | None = None  # (발화, 턴 id)
        for turn in [*session.turns, None]:
            if pending is not None and (turn is None or turn.role == "user"):
                await _turn(memory, scope, index, pending, None, created)
                pending = None
            if turn is None:
                break
            if turn.role == "user":
                index += 1
                pending = (turn.text, turn.turn_id)
            elif pending is not None:
                await _turn(memory, scope, index, pending, (turn.text, turn.turn_id), created)
                pending = None
        await memory.consolidate(scope)


async def _turn(
    memory: MemoryService, scope: MemoryScope, index: int, user: tuple[str, str], answer: tuple[str, str] | None,
    created: datetime | None,
) -> None:
    item = await memory.get(await memory.record_turn(index, user[0], answer[0] if answer else "", scope))
    if item is None:
        return
    item.tags = [f"session:{scope.session_id}", f"turn:{user[1]}"] + ([f"turn:{answer[1]}"] if answer else [])
    if created is not None:
        item.created_at = item.occurred_at = created
    await memory.store.store(item)


# ── 질문 ──────────────────────────────────────────────────────────────────────


def _item_session(item: MemoryItem) -> str | None:
    return item.scope.session_id


def _item_turns(item: MemoryItem) -> set[str]:
    return {t.removeprefix("turn:") for t in item.tags if t.startswith("turn:")}


async def ask(memory: MemoryService, question: BenchmarkQuestion, k: int) -> QuestionResult:
    scope = MemoryScope(user_id=USER, agent_id="main")
    items = await memory.recall(question.question, scope, limit=k)
    session_hit = any(_item_session(i) in question.evidence_session_ids for i in items)
    turn_hit: bool | None = None
    if question.evidence_turn_ids:
        turn_hit = any(_item_turns(i) & question.evidence_turn_ids for i in items)
    return QuestionResult(
        question_id=question.question_id,
        question_type=question.question_type,
        retrieved=[i.content for i in items],
        session_hit=session_hit,
        turn_hit=turn_hit,
    )


Judge = Callable[[BenchmarkQuestion, list[str]], Awaitable[tuple[str, bool]]]


async def run_benchmark(
    name: str,
    questions: list[BenchmarkQuestion],
    memory_factory: Callable[[], MemoryService],
    *,
    k: int = 5,
    mode: str = "raw",
    judge: Judge | None = None,
) -> BenchmarkReport:
    """질문마다 새 메모리에 그 질문의 대화 전체를 넣고 묻는다. 질문 간 오염이 없고 순서에 의존하지 않는다."""
    results: list[QuestionResult] = []
    for question in questions:
        memory = memory_factory()
        if mode == "turns":
            await ingest_turns(memory, question)
        else:
            await ingest_raw(memory, question)
        result = await ask(memory, question, k)
        if judge is not None:
            result.predicted, result.correct = await judge(question, result.retrieved)
        results.append(result)
    return BenchmarkReport(name=name, mode=mode, k=k, results=results)


def format_benchmark(report: BenchmarkReport) -> str:
    lines = [f"{report.name} mode={report.mode} k={report.k} n={len(report.results)}"]
    lines.append(f"{'type':<28}{'n':>5}{'sess@k':>9}{'turn@k':>9}{'acc':>7}")
    for qtype, m in report.by_type().items():
        lines.append(
            f"{qtype:<28}{m['n']:>5}{_fmt(m['session_recall']):>9}{_fmt(m['turn_recall']):>9}{_fmt(m['accuracy']):>7}"
        )
    total = report.by_type()
    if total:
        n = sum(int(m["n"] or 0) for m in total.values())
        sess = sum(r.session_hit for r in report.results) / len(report.results)
        lines.append(f"{'all':<28}{n:>5}{_fmt(sess):>9}")
    return "\n".join(lines)


def _fmt(v: float | int | None) -> str:
    return "-" if v is None else f"{v:.2f}"


def _parse_date(text: str) -> datetime | None:
    """'2023/05/20 (Sat) 02:21' 이나 '1:56 pm on 8 May, 2023' 처럼 제각각이라 실패하면 None(생성 시각)."""
    for fmt in ("%Y/%m/%d (%a) %H:%M", "%Y/%m/%d", "%I:%M %p on %d %B, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    return None
