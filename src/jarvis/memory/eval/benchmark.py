"""[memory] 외부 벤치마크의 긴 다중 세션 대화를 비교군별로 담고 질문으로 회상해 증거 재현율과 정답률을 잰다."""

import random
import asyncio
from typing import Any
from datetime import datetime
from dataclasses import asdict, dataclass, field
from collections.abc import Awaitable, Callable, Sequence

from jarvis.memory.memory_service import MemoryService, turn_contents, turn_item_id
from jarvis.memory.long_term.fact_source import SOURCE_EPISODE, with_source
from jarvis.memory.eval.rag_baseline import RagIndex, chunk_sessions
from jarvis.model_layer.embeddings import Embedder
from jarvis.memory.memory_types import MemoryItem
from jarvis.memory.scope import MemoryScope

USER = "benchmark"

# 비교군(Memory Tax, He et al. 2026 의 net value 분해를 Jarvis 에 맞춘 것)
#   rag: 원문 턴 조각을 임베딩 코사인 top-k 로만 찾는 기준선(메모리 없음)
#   raw: 턴마다 일화 하나를 Jarvis 합성 점수로 회상(구성 없음, 회상 방식만 Jarvis)
#   turns: 실서비스 경로. 발화와 답을 턴 일화로 쓰고 세션 끝에 공고화(추출기를 주면 LLM 이 사실을 뽑는다)
#   turns+src: turns 와 같은 메모리에서 추출 사실의 출처 턴을 후보에 더해 질의 관련도 하나로 다시 매긴다(src-aug)
#   turns+excerpt: 처음 시도한 방식. 추출 사실 아래 출처 턴의 해당 부분(최대 300자)을 붙인다
#   turns+src+cov: turns+src 의 회상 k 개가 질문의 대상을 다 덮지 못하면 빠진 대상으로 다시 찾아 k 개 안에 섞는다
# 증거 재현율은 LLM 없이 계산하고, 정답 여부(accuracy)는 judge 를 줄 때만 판정한다.
MODES = ("rag", "raw", "turns", "turns+src", "turns+excerpt", "turns+src+cov")
# 노출 예산으로 자르기 전에 받는 후보 수. 짧은 사실이 많은 비교군도 예산을 채우게 넉넉히 받는다. 예산이 없으면 k 개만
CANDIDATES = 150


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
    corpus_id: str = ""  # 같은 대화를 공유하는 질문 묶음. 비우면 질문마다 대화가 따로다
    choices: list[str] = field(default_factory=list)  # 객관식이면 보기(정답 포함), 아니면 빈 목록

    @property
    def corpus(self) -> str:
        return self.corpus_id or self.question_id


@dataclass
class QuestionResult:
    question_id: str
    question_type: str
    retrieved: list[str]  # 모델에 보인 항목 내용(예산으로 자른 뒤)
    session_hit: bool | None  # 상위 항목에 증거 세션이 있는가. 세션 증거가 없는 벤치마크는 None
    turn_hit: bool | None  # 턴 단위 증거가 있는 벤치마크만
    correct: bool | None = None  # judge 를 줄 때만
    predicted: str | None = None
    exposed_chars: int = 0  # 모델에 보인 글자 수(답 프롬프트의 기억 칸)


@dataclass
class BenchmarkReport:
    name: str
    mode: str
    k: int
    results: list[QuestionResult]
    budget: int | None = None

    def by_type(self) -> dict[str, dict[str, float | int | None]]:
        groups: dict[str, list[QuestionResult]] = {}
        for r in self.results:
            groups.setdefault(r.question_type, []).append(r)
        return {qtype: _rates(rs) for qtype, rs in sorted(groups.items())}

    def summary(self) -> dict[str, float | int | None]:
        """전체 지표와 노출량(평균 항목 수, 평균 글자 수)."""
        out = _rates(self.results)
        n = len(self.results) or 1
        out["mean_items"] = round(sum(len(r.retrieved) for r in self.results) / n, 2)
        out["mean_chars"] = round(sum(r.exposed_chars for r in self.results) / n, 1)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "mode": self.mode, "k": self.k, "budget": self.budget,
                "summary": self.summary(), "by_type": self.by_type(), "results": [asdict(r) for r in self.results]}


def _rates(rs: list[QuestionResult]) -> dict[str, float | int | None]:
    return {
        "n": len(rs),
        "session_recall": _mean([r.session_hit for r in rs]),
        "turn_recall": _mean([r.turn_hit for r in rs]),
        "accuracy": _mean([r.correct for r in rs]),
    }


def _mean(values: Sequence[bool | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) / len(known) if known else None


def sample(questions: list[BenchmarkQuestion], limit: int | None, seed: int = 0) -> list[BenchmarkQuestion]:
    if limit is None or limit >= len(questions):
        return questions
    rng = random.Random(seed)
    return rng.sample(questions, limit)


def stratified_sample(
    questions: list[BenchmarkQuestion],
    limit: int | None,
    seed: int = 0,
    *,
    max_corpora: int | None = None,
    key: Callable[[BenchmarkQuestion], str] = lambda q: q.question_type,
) -> list[BenchmarkQuestion]:
    """유형별로 고르게 limit 개. 유형마다 섞은 뒤 돌아가며 하나씩 뽑아, 작은 유형도 빠지지 않는다.

    max_corpora 를 주면 대화 묶음을 먼저 그만큼 고른다(대화 하나를 담는 비용이 질문보다 크다).
    같은 seed 면 같은 표본이고, 결과는 원래 순서를 지킨다.
    """
    rng = random.Random(seed)
    pool = questions
    if max_corpora is not None:
        corpora = sorted({q.corpus for q in questions})
        chosen = set(rng.sample(corpora, min(max_corpora, len(corpora))))
        pool = [q for q in questions if q.corpus in chosen]
    if limit is None or limit >= len(pool):
        return pool
    strata: dict[str, list[BenchmarkQuestion]] = {}
    for q in pool:
        strata.setdefault(key(q), []).append(q)
    queues = [rng.sample(group, len(group)) for _, group in sorted(strata.items())]
    picked: set[str] = set()
    while len(picked) < limit:
        for queue in queues:
            if queue and len(picked) < limit:
                picked.add(queue.pop().question_id)
    return [q for q in pool if q.question_id in picked]


# ── 메모리에 넣기 ──────────────────────────────────────────────────────────────


def raw_text(turn: BenchmarkTurn) -> str:
    return f"[{turn.role}] {turn.text}"


async def ingest_raw(memory: MemoryService, question: BenchmarkQuestion) -> None:
    """턴마다 일화 하나. 세션과 턴 id 를 태그로 남겨 증거 재현율을 계산한다."""
    for session in question.sessions:
        scope = MemoryScope(user_id=USER, agent_id="main", session_id=session.session_id)
        created = _parse_date(session.date)
        for turn in session.turns:
            await memory.remember(
                raw_text(turn),
                source="benchmark",
                scope=scope,
                tags=[f"session:{session.session_id}", f"turn:{turn.turn_id}"],
                created_at=created,
            )


def exchanges(session: BenchmarkSession) -> list[tuple[int, BenchmarkTurn, BenchmarkTurn | None]]:
    """사용자 발화와 바로 뒤의 답을 (턴 번호, 발화, 답) 으로 묶는다. 사용자 발화 없이 온 답은 버린다."""
    out: list[tuple[int, BenchmarkTurn, BenchmarkTurn | None]] = []
    for turn in session.turns:
        if turn.role == "user":
            out.append((len(out) + 1, turn, None))
        elif out and out[-1][2] is None:
            out[-1] = (out[-1][0], out[-1][1], turn)
    return out


async def ingest_turns(memory: MemoryService, question: BenchmarkQuestion) -> None:
    """사용자 발화와 바로 뒤의 답을 턴 일화 하나로(긴 답은 조각 일화를 더해). 턴 id 를 태그로 남긴다."""
    for session in question.sessions:
        scope = MemoryScope(user_id=USER, agent_id="main", session_id=session.session_id)
        created = _parse_date(session.date)
        for index, user, answer in exchanges(session):
            await memory.record_turn(index, user.text, answer.text if answer else "", scope)
            tags = [f"session:{session.session_id}", f"turn:{user.turn_id}"] + (
                [f"turn:{answer.turn_id}"] if answer else []
            )
            parts = len(turn_contents(user.text, answer.text if answer else "", memory.answer_parts)) - 1
            for part in range(parts + 1):
                item = await memory.get(turn_item_id(scope, index, part))
                if item is None:
                    continue
                item.tags = tags if part == 0 else [tags[0]] + tags[2:]
                if created is not None:
                    item.created_at = item.occurred_at = created
                await memory.store.store(item)
        await memory.consolidate(scope)


def ingest_texts(question: BenchmarkQuestion, mode: str, answer_parts: int) -> list[str]:
    """그 비교군이 담을 때 임베딩하는 글자 그대로. 캐시를 묶어서 미리 채우는 데 쓴다(추출 사실은 빼고)."""
    if mode == "rag":
        return [c.text for c in chunk_sessions(question.sessions)]
    if mode == "raw":
        return [raw_text(t) for s in question.sessions for t in s.turns]
    return [
        text
        for s in question.sessions
        for _, user, answer in exchanges(s)
        for text in turn_contents(user.text, answer.text if answer else "", answer_parts)
    ]


# ── 질문 ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Retrieved:
    text: str
    session_id: str | None
    turn_ids: frozenset[str]


def _item_turns(item: MemoryItem) -> frozenset[str]:
    return frozenset(t.removeprefix("turn:") for t in item.tags if t.startswith("turn:"))


async def recall_items(
    memory: MemoryService, question: BenchmarkQuestion, limit: int, mode: str = "raw", k: int | None = None
) -> list[Retrieved]:
    """추출 사실의 세션과 턴은 출처 턴의 것으로 센다. 증거 턴에서 뽑은 사실이 떠오르면 증거를 찾은 것이다.

    k 는 핵심 사실을 뺀 회상 자리 수다. turns+src+cov 는 실서비스처럼 그 k 개 안에서 커버리지를 맞춘다.
    """
    scope = MemoryScope(user_id=USER, agent_id="main")
    if mode == "turns+src+cov":
        found = await memory.recall_with_sources(question.question, scope, limit=limit)
        fixed_ids = {f.id for f in await memory.fixed_facts(scope)}
        pool = [i for i in found if i.id not in fixed_ids][: k or limit]
        covered = await memory.cover(await memory.entities(question.question), pool, scope, k or limit,
                                     exclude=fixed_ids)
        items = [i for i in found if i.id in fixed_ids] + covered
    elif mode == "turns+src":
        items = await memory.recall_with_sources(question.question, scope, limit=limit)
    else:
        items = await memory.recall(question.question, scope, limit=limit)
    excerpts = await memory.source_excerpts(items) if mode == "turns+excerpt" else {}
    out: list[Retrieved] = []
    for item in items:
        origin = item
        if item.metadata.get(SOURCE_EPISODE):
            origin = await memory.get(str(item.metadata[SOURCE_EPISODE])) or item
        out.append(Retrieved(with_source(item.content, excerpts.get(item.id)), origin.scope.session_id,
                             _item_turns(origin)))
    return out


async def _with_fixed(memory: MemoryService, found: list[Retrieved], k: int) -> list[Retrieved]:
    """실서비스 블록: 핵심 사실 뒤에 그와 겹치지 않는 회상 k 개(observe 와 같은 규칙)."""
    facts = await memory.fixed_facts(MemoryScope(user_id=USER, agent_id="main"))
    texts = {f.content for f in facts}
    head = [Retrieved(f.content, None, frozenset()) for f in facts]
    return head + [r for r in found if r.text not in texts][:k]


def fit_budget(retrieved: Sequence[Retrieved], k: int, budget: int | None) -> list[Retrieved]:
    """예산이 없으면 상위 k 개. 있으면 순위대로 담다가 글자 예산을 넘는 항목은 남은 만큼 잘라 넣고 멈춘다."""
    if budget is None:
        return list(retrieved[:k])
    out: list[Retrieved] = []
    left = budget
    for r in retrieved:
        if left <= 0:
            break
        out.append(r if len(r.text) <= left else Retrieved(r.text[:left], r.session_id, r.turn_ids))
        left -= len(r.text)
    return out


def score(question: BenchmarkQuestion, retrieved: Sequence[Retrieved]) -> QuestionResult:
    session_hit = (
        any(r.session_id in question.evidence_session_ids for r in retrieved) if question.evidence_session_ids else None
    )
    turn_hit = any(r.turn_ids & question.evidence_turn_ids for r in retrieved) if question.evidence_turn_ids else None
    return QuestionResult(
        question_id=question.question_id,
        question_type=question.question_type,
        retrieved=[r.text for r in retrieved],
        session_hit=session_hit,
        turn_hit=turn_hit,
        exposed_chars=sum(len(r.text) for r in retrieved),
    )


async def ask(memory: MemoryService, question: BenchmarkQuestion, k: int) -> QuestionResult:
    return score(question, await recall_items(memory, question, k))


Judge = Callable[[BenchmarkQuestion, list[str]], Awaitable[tuple[str, bool]]]
Warm = Callable[[list[str]], Awaitable[None]]


async def run_benchmark(
    name: str,
    questions: list[BenchmarkQuestion],
    memory_factory: Callable[[], MemoryService],
    *,
    k: int = 5,
    mode: str = "raw",
    judge: Judge | None = None,
    embedder: Embedder | None = None,
    budget: int | None = None,
    warm: Warm | None = None,
    concurrency: int = 1,
    fixed: bool = False,
) -> BenchmarkReport:
    """대화 묶음마다 새 메모리에 그 대화 전체를 넣고 묶음의 질문을 묻는다. 묶음 간 오염이 없고 순서에 의존하지 않는다.

    rag 는 embedder 가 필요하다. budget(글자)을 주면 비교군마다 노출량이 같도록 k 대신 예산으로 자른다.
    fixed 면 실서비스처럼 핵심 사실 블록을 앞에 두고 회상 k 개를 잇는다(메모리 비교군만).
    """
    if mode not in MODES:
        raise ValueError(f"mode 는 {MODES} 중 하나다: {mode}")
    if mode == "rag" and embedder is None:
        raise ValueError("rag 비교군은 embedder 가 필요하다")
    corpora: dict[str, list[BenchmarkQuestion]] = {}
    for q in questions:
        corpora.setdefault(q.corpus, []).append(q)
    gate = asyncio.Semaphore(max(1, concurrency))
    # 핵심 사실과 겹친 회상은 빠지므로 그만큼 더 받는다(observe 와 같다)
    limit = CANDIDATES if budget is not None else k + (memory_factory().fixed_facts_limit if fixed else 0)

    async def one_corpus(group: list[BenchmarkQuestion]) -> list[QuestionResult]:
        async with gate:
            head = group[0]
            out: list[QuestionResult] = []
            if mode == "rag":
                assert embedder is not None  # 위에서 막았다
                index = RagIndex(embedder)
                if warm is not None:
                    await warm(ingest_texts(head, mode, 0))
                await index.ingest(head)
                for q in group:
                    chunks = await index.search(q.question, limit)
                    found = [Retrieved(c.text, c.session_id, frozenset(c.turn_ids)) for c in chunks]
                    out.append(score(q, fit_budget(found, k, budget)))
            else:
                memory = memory_factory()
                if warm is not None:
                    await warm(ingest_texts(head, mode, memory.answer_parts))
                if mode == "raw":
                    await ingest_raw(memory, head)
                else:
                    await ingest_turns(memory, head)
                for q in group:
                    found = await recall_items(memory, q, limit, mode, k)
                    if fixed:
                        out.append(score(q, await _with_fixed(memory, found, k)))
                    else:
                        out.append(score(q, fit_budget(found, k, budget)))
            if judge is not None:
                for q, result in zip(group, out, strict=True):
                    result.predicted, result.correct = await judge(q, result.retrieved)
            return out

    done = await asyncio.gather(*(one_corpus(g) for g in corpora.values()))
    by_id = {r.question_id: r for rs in done for r in rs}
    return BenchmarkReport(name=name, mode=mode, k=k, results=[by_id[q.question_id] for q in questions], budget=budget)


def format_benchmark(report: BenchmarkReport) -> str:
    budget = f" budget={report.budget}" if report.budget is not None else ""
    lines = [f"{report.name} mode={report.mode} k={report.k}{budget} n={len(report.results)}"]
    lines.append(f"{'type':<28}{'n':>5}{'sess@k':>9}{'turn@k':>9}{'acc':>7}")
    for qtype, m in [*report.by_type().items(), ("all", report.summary())]:
        lines.append(
            f"{qtype:<28}{m['n']:>5}{_fmt(m['session_recall']):>9}{_fmt(m['turn_recall']):>9}{_fmt(m['accuracy']):>7}"
        )
    s = report.summary()
    lines.append(f"노출: 평균 {s['mean_items']} 항목, {s['mean_chars']} 자")
    return "\n".join(lines)


def _fmt(v: float | int | None) -> str:
    return "-" if v is None else f"{v:.2f}"


def _parse_date(text: str) -> datetime | None:
    """'2023/05/20 (Sat) 02:21', '1:56 pm on 8 May, 2023', ISO 처럼 제각각이라 실패하면 None(생성 시각)."""
    for fmt in ("%Y/%m/%d (%a) %H:%M", "%Y/%m/%d", "%I:%M %p on %d %B, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except ValueError:
            continue
    try:
        # 시간대가 붙은 ISO(위키, 커밋)는 다른 항목과 비교할 수 있게 시간대를 뗀다
        return datetime.fromisoformat(text.strip().replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
