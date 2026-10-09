"""외부 벤치마크 공통 실행기. 긴 다중 세션 대화를 메모리에 넣고 질문으로 회상해 증거 재현율을 잰다.

두 모드가 있다.
- raw: 턴마다 일화 항목 하나. LLM 없이 검색 품질만 본다(기본, 빠름)
- full: 하네스처럼 observe 로 흘리고 세션 끝에 요약과 공고화. 실제 LLM 이 필요해 비싸다

증거 재현율은 LLM 없이 계산한다. 정답 포함 여부(accuracy)는 --judge 일 때만 LLM 으로 판정한다.
"""

import random
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from jarvis.memory.manager import MemoryManager
from jarvis.memory.scope import MemoryScope
from jarvis.memory.types import MemoryItem
from jarvis.model_layer.types import AssistantMessage, Message, TextContent, UserMessage

USER = "benchmark"


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


async def ingest_raw(memory: MemoryManager, question: BenchmarkQuestion) -> None:
    """턴마다 일화 하나. 세션과 턴 id 를 태그로 남겨 증거 재현율을 계산한다."""
    for session in question.sessions:
        scope = MemoryScope(user_id=USER, agent_id="main", session_id=session.session_id)
        created = _parse_date(session.date)
        for turn in session.turns:
            await memory.remember(
                f"[{turn.role}] {turn.text}",
                source="session_end",
                scope=scope,
                tags=[f"session:{session.session_id}", f"turn:{turn.turn_id}"],
                created_at=created,
            )


Summarize = Callable[[str, list[Message], MemoryScope], Awaitable[str | None]]


async def ingest_full(memory: MemoryManager, question: BenchmarkQuestion, save_session: Summarize) -> None:
    """하네스처럼: user 턴마다 observe(컴팩션 포함), 세션 끝에 종료 요약과 공고화."""
    for session in question.sessions:
        scope = MemoryScope(user_id=USER, agent_id="main", session_id=session.session_id)
        context = {"user_id": USER, "agent_id": "main", "session_id": session.session_id}
        history: list[Message] = []
        for turn in session.turns:
            if turn.role == "user":
                history.append(UserMessage(content=turn.text))
                await memory.observe(history, context)
            else:
                history.append(AssistantMessage(content=[TextContent(text=turn.text)]))
        await save_session(session.session_id, history, scope)
        await memory.consolidate(scope)


# ── 질문 ──────────────────────────────────────────────────────────────────────


def _item_session(item: MemoryItem) -> str | None:
    return item.scope.session_id


def _item_turns(item: MemoryItem) -> set[str]:
    return {t.removeprefix("turn:") for t in item.tags if t.startswith("turn:")}


async def ask(memory: MemoryManager, question: BenchmarkQuestion, k: int) -> QuestionResult:
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
    memory_factory: Callable[[], MemoryManager],
    *,
    k: int = 5,
    mode: str = "raw",
    save_session: Summarize | None = None,
    judge: Judge | None = None,
) -> BenchmarkReport:
    """질문마다 새 메모리에 그 질문의 대화 전체를 넣고 묻는다. 질문 간 오염이 없고 순서에 의존하지 않는다."""
    results: list[QuestionResult] = []
    for question in questions:
        memory = memory_factory()
        if mode == "full":
            if save_session is None:
                raise ValueError("full mode needs save_session")
            await ingest_full(memory, question, save_session)
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
