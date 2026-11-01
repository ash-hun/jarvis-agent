"""[core] 쌓인 성공은 절차 초안이나 개정으로, 쌓인 실패는 반성으로 거른 수정 초안으로 저장한다(같은 근거는 한 번만)."""

import hashlib
from typing import TYPE_CHECKING
from dataclasses import dataclass, replace

from jarvis.core.procedures.procedures_store import (
    KIND_PROCEDURE,
    KIND_TASK_PATTERN,
    STATUS_DRAFT,
    Procedure,
    ProcedureStore,
)
from jarvis.core.procedures.reflect import ACTION_NONE, ACTION_PATTERN, Attempt, FailureCase, Reflection, Reflector
from jarvis.core.procedures.detect import DEFAULT_MIN_TOOL_CALLS, TaskSpan, ToolStep, find_spans
from jarvis.core.procedures.distill import FALLBACK_NAME, Distiller, ProcedureDraft, slugify
from jarvis.core.procedures.converge import plan_convergence
from jarvis.core.procedures.update_guard import check
from jarvis.core.procedures.plan import valid_plan
from jarvis.model_layer.model_types import Message
from jarvis.common.logger import get_logger
from jarvis.memory.scope import MAIN_AGENT

if TYPE_CHECKING:
    from jarvis.memory.long_term.refine import Candidate, FailureBatch
    from jarvis.memory.memory_service import MemoryService
    from jarvis.memory.memory_types import MemoryItem
    from jarvis.memory.scope import MemoryScope

SUFFIX_LEN = 6
# 에이전트 하나가 가질 수 있는 절차와 작업 패턴 초안 파일 수. 넘으면 새 항목은 만들지 않고 있는 것만 고친다
MAX_PER_AGENT = 30
# 유휴 틱 하나에서 반성하는 실패 묶음 수. 묶음 하나가 LLM 을 많아야 두 번(거부 뒤 한 번 더) 부른다
MAX_REFLECTIONS_PER_TICK = 2
PATTERN_PREFIX = "pattern-"
ACCEPTED = "accepted"
REFERENCE = "reference"  # 턴 일화 metadata: 판정에 쓴 정답(채점이 있는 실험에서만). 거름망이 누출을 막는 데 쓴다

logger = get_logger(__name__)


@dataclass(frozen=True)
class ReflectionOutcome:
    """반성 한 번의 결과. kind 는 procedure | task_pattern | no_change | refused | blocked."""

    task_type: str
    kind: str
    name: str = ""
    proposals: tuple[Reflection, ...] = ()  # 시도한 제안 순서대로. 거부 이유를 받고 다시 낸 제안까지
    reasons: tuple[str, ...] = ()  # 거름망이 막은 이유


def source_key(session_id: str, span: TaskSpan) -> str:
    return f"{session_id}#{span.start}"


def unique_name(name: str, source: str, existing: dict[str, str]) -> str:
    """이름이 같은 절차가 다른 출처면 출처 해시를 붙여 구분한다. 같은 출처면 그 이름 그대로(재실행)."""
    taken = existing.get(name)
    if taken is None or taken == source:
        return name
    return f"{name}-{hashlib.sha1(source.encode()).hexdigest()[:SUFFIX_LEN]}"


def build_procedure(draft: ProcedureDraft, span: TaskSpan, source: str, name: str) -> Procedure:
    lines = [f"요청 예: {span.request[:200]}"]
    if draft.parameters:
        lines.append(f"입력: {draft.parameters}")
    lines.append("이번 입력: {{args}}")
    lines.append("")
    lines.append("절차:")
    lines.extend(f"{i}. {step}" for i, step in enumerate(draft.steps, 1))
    # 모델이 낸 계획은 학습한 작업에서 쓴 도구와 선언한 입력만 쓸 때 남긴다. 아니면 레시피만 둔다
    runnable = valid_plan(draft.plan, draft.inputs, span.tool_names)
    return Procedure(
        name=name,
        description=draft.description,
        body="\n".join(lines) + "\n",
        status=STATUS_DRAFT,
        source=source,
        tools=span.tool_names,
        parameters=draft.parameters,
        inputs=draft.inputs if runnable else (),
        plan=draft.plan if runnable else (),
    )


def reflected_procedure(proposal: Reflection, task_type: str, source: str, name: str, agent: str) -> Procedure:
    body = f"이번 입력: {{{{args}}}}\n\n절차:\n{proposal.content.strip()}\n"
    return Procedure(
        name=name, description=proposal.when.strip() or f"{task_type} 작업 방법", body=body, source=source,
        tools=(task_type,), agent=agent,
    )


def pattern_draft(proposal: Reflection, source: str, agent: str) -> Procedure:
    """이름은 제안 이름에서. 영문이 없으면 내용 해시로 정해 같은 제안은 같은 파일이다.
    main 이 아닌 에이전트는 이름에 에이전트를 넣는다. 파일 이름이 키라 다른 에이전트의 초안을 덮지 않게 한다."""
    slug = slugify(proposal.name)
    if slug == FALLBACK_NAME:
        slug = hashlib.sha1(f"{source}|{proposal.when}|{proposal.content}".encode()).hexdigest()[:SUFFIX_LEN]
    owner = f"{slugify(agent)}-" if agent and agent != MAIN_AGENT else ""
    return Procedure(
        name=PATTERN_PREFIX + owner + slug, description=proposal.when.strip(), body=proposal.content.strip() + "\n",
        source=source, agent=agent, kind=KIND_TASK_PATTERN,
        keywords=tuple(k.strip() for k in proposal.keywords if k.strip()),
    )


def episode_span(candidate: "Candidate") -> TaskSpan | None:
    """후보의 가장 최근 성공 중 도구 단계가 남은 일화 하나를 증류기 입력으로 바꾼다. 그런 일화가 없으면 None."""
    from jarvis.memory.memory_service import TURN_STEPS, turn_parts

    for episode in reversed(candidate.evidence):
        steps = tuple(
            ToolStep(name=str(s["name"]), args=dict(s.get("args") or {}))
            for s in episode.metadata.get(TURN_STEPS) or [] if isinstance(s, dict) and s.get("name")
        )
        request, outcome = turn_parts(episode)
        if steps and request.strip() and outcome.strip():
            return TaskSpan(start=0, request=request.strip(), steps=steps, outcome=outcome.strip())
    return None


def failure_case(batch: "FailureBatch", procedure: Procedure | None) -> FailureCase:
    from jarvis.memory.long_term.refine import OVERFLOW
    from jarvis.memory.memory_service import turn_parts

    attempts = tuple(
        Attempt(*turn_parts(e), overflow=bool(e.metadata.get(OVERFLOW))) for e in batch.evidence
    )
    references = tuple(str(e.metadata[REFERENCE]) for e in batch.evidence if e.metadata.get(REFERENCE))
    return FailureCase(batch.agent_id, batch.task_type, attempts, procedure.body if procedure else "", references)



class ProcedureLearner:
    def __init__(
        self,
        store: ProcedureStore,
        distiller: Distiller,
        min_tool_calls: int = DEFAULT_MIN_TOOL_CALLS,
        memory: "MemoryService | None" = None,
        reflector: Reflector | None = None,
        *,
        guard: bool = True,
        max_per_agent: int = MAX_PER_AGENT,
        max_reflections: int = MAX_REFLECTIONS_PER_TICK,
    ) -> None:
        self._store = store
        self._distill = distiller
        self._min_tool_calls = min_tool_calls
        self._memory = memory
        self._reflector = reflector
        # 끄면 제안을 행동 그대로 쓴다. 거름망의 효과를 재는 실험용이다
        self._guard = guard
        self._max_per_agent = max_per_agent
        self._max_reflections = max_reflections

    @property
    def memory(self) -> "MemoryService | None":
        return self._memory

    def converge(self) -> int:
        """옛 세대 파일을 (에이전트, 작업 종류)당 하나로. 밀려난 파일은 보관한다. 고친 묶음 수."""
        plans = plan_convergence(self._store.list())
        for plan in plans:
            # 남길 파일을 먼저 쓴다. 보관 중에 죽어도 다음 호출이 남은 옛 파일을 다시 묶는다
            self._store.save(plan.keep)
            for name in plan.archive:
                self._store.archive(name)
            logger.info(f"[ProcedureLearner] converged {plan.keep.source} → {plan.keep.name}, archived {plan.archive}")
        return len(plans)

    async def refine(self, scope: "MemoryScope") -> list[str]:
        """통합 끝에 부른다. 성공은 증류하고 실패는 반성한다. 새로 쓰거나 고친 초안 이름."""
        if self._memory is None:
            return []
        from jarvis.memory.long_term.refine import candidates

        self.converge()
        resolved = scope.with_session(None)
        items = await self._episodes(resolved)
        written = await self._distill_candidates(candidates(items, resolved))
        if self._reflector is not None:
            written += [o.name for o in await self._reflect_items(items, resolved) if o.name]
        return written

    async def reflect(self, scope: "MemoryScope") -> list[ReflectionOutcome]:
        """실패 반성만. 유휴 틱당 상한만큼만 LLM 을 부른다."""
        if self._memory is None or self._reflector is None:
            return []
        resolved = scope.with_session(None)
        return await self._reflect_items(await self._episodes(resolved), resolved)

    async def _episodes(self, scope: "MemoryScope") -> list["MemoryItem"]:
        from jarvis.memory.memory_service import REFINE_FILTER, REFINE_SCAN_LIMIT
        from jarvis.memory.access import Readable
        from jarvis.memory import MemoryKind

        assert self._memory is not None
        return await self._memory.store.recent(
            scope, kinds=[MemoryKind.EPISODIC], limit=REFINE_SCAN_LIMIT,
            readable=Readable.own(scope.agent_id), where=REFINE_FILTER,
        )

    async def _distill_candidates(self, found: list["Candidate"]) -> list[str]:
        """(에이전트, 작업 종류)당 파일 하나. 새 세대는 초안이면 덮고, 승인됐으면 개정 초안으로 붙인다."""
        procedures = self._store.list()
        by_source = {p.source: p for p in procedures}
        existing = {p.name: p.source for p in procedures}
        written: list[str] = []
        for candidate in found:
            current = by_source.get(candidate.source)
            if current is not None and _seen(current) >= candidate.generation:
                continue
            if current is None and not self._has_room(candidate.agent_id, procedures):
                logger.info(f"[ProcedureLearner] cap reached for {candidate.agent_id}, skip {candidate.task_type}")
                continue
            span = episode_span(candidate)
            if span is None:
                continue
            draft = await self._distill(span)
            if draft is None:
                continue
            name = current.name if current is not None else unique_name(draft.name, candidate.source, existing)
            fresh = replace(
                build_procedure(draft, span, candidate.source, name),
                agent=candidate.agent_id, generation=candidate.generation,
            )
            saved = self._place(current, fresh)
            procedures = [p for p in procedures if p.name != name] + [saved]
            by_source[candidate.source] = saved
            existing[name] = candidate.source
            written.append(name)
        return written

    def _place(self, current: Procedure | None, fresh: Procedure) -> Procedure:
        """승인된 절차는 개정 초안 칸에, 아니면 그 자리에 쓴다."""
        saved = replace(current, revision=fresh) if current is not None and current.approved else fresh
        self._store.save(saved)
        return saved

    def _has_room(self, agent: str, procedures: list[Procedure]) -> bool:
        return sum(1 for p in procedures if (p.agent or MAIN_AGENT) == (agent or MAIN_AGENT)) < self._max_per_agent

    async def _reflect_items(self, items: list["MemoryItem"], scope: "MemoryScope") -> list[ReflectionOutcome]:
        from jarvis.memory.long_term.refine import BLOCKED, failures

        outcomes: list[ReflectionOutcome] = []
        asked = 0
        for batch in failures(items, scope):
            if batch.blocked:
                # 잇달아 거부된 종류는 LLM 을 부르지 않고 이번 실패만 표시한다
                await self._mark(batch, BLOCKED)
                outcomes.append(ReflectionOutcome(batch.task_type, BLOCKED))
                continue
            if asked >= self._max_reflections:
                continue
            asked += 1
            outcome = await self._reflect_batch(batch)
            await self._mark(batch, ACCEPTED if outcome.kind in (KIND_PROCEDURE, KIND_TASK_PATTERN) else outcome.kind)
            outcomes.append(outcome)
        return outcomes

    async def _reflect_batch(self, batch: "FailureBatch") -> ReflectionOutcome:
        """거부되면 이유를 한 번 돌려주고, 또 거부되면 아무것도 쓰지 않는다."""
        from jarvis.memory.long_term.refine import REFUSED

        assert self._reflector is not None
        procedures = self._store.list()
        current = next((p for p in procedures if p.source == batch.source), None)
        case = failure_case(batch, current)
        proposals: list[Reflection] = []
        reasons: list[str] = []
        for _ in range(2):
            proposal = await self._reflector(case, reasons[-1] if reasons else "")
            if proposal is None:
                reasons.append("출력이 JSON 스키마(scope, action, content)에 맞지 않는다")
                if not self._guard:
                    break
                continue
            proposals.append(proposal)
            target = self._target(proposal, batch, procedures)
            room = target is not None or self._has_room(batch.agent_id, procedures)
            reason = check(proposal, case, room) if self._guard else None
            if reason is None:
                name = self._apply(proposal, batch, target)
                kind = KIND_TASK_PATTERN if proposal.action == ACTION_PATTERN else KIND_PROCEDURE
                kind = kind if name else ACTION_NONE
                return ReflectionOutcome(batch.task_type, kind, name, tuple(proposals), tuple(reasons))
            reasons.append(reason)
        return ReflectionOutcome(batch.task_type, REFUSED, "", tuple(proposals), tuple(reasons))

    def _target(self, proposal: Reflection, batch: "FailureBatch", procedures: list[Procedure]) -> Procedure | None:
        """제안이 고칠 기존 항목. 절차는 같은 출처, 작업 패턴은 같은 이름의 초안."""
        if proposal.action == ACTION_PATTERN:
            name = pattern_draft(proposal, batch.source, batch.agent_id).name
            return next((p for p in procedures if p.name == name), None)
        return next((p for p in procedures if p.source == batch.source), None)

    def _apply(self, proposal: Reflection, batch: "FailureBatch", target: Procedure | None) -> str:
        """제안을 초안으로 쓴다. 기록하지 않으면 빈 문자열."""
        if proposal.action == ACTION_NONE:
            return ""
        if proposal.action == ACTION_PATTERN:
            draft = pattern_draft(proposal, batch.source, batch.agent_id)
            self._store.save(draft)
            return draft.name
        existing = {p.name: p.source for p in self._store.list()}
        name = target.name if target is not None else unique_name(
            slugify(proposal.name or batch.task_type), batch.source, existing
        )
        fresh = reflected_procedure(proposal, batch.task_type, batch.source, name, batch.agent_id)
        fresh = replace(fresh, generation=_seen(target) if target is not None else 0)
        return self._place(target, fresh).name

    async def _mark(self, batch: "FailureBatch", result: str) -> None:
        from jarvis.memory.long_term.refine import REFLECT_BATCH, REFLECTED

        assert self._memory is not None
        for episode in batch.evidence:
            episode.metadata[REFLECTED] = result
            episode.metadata[REFLECT_BATCH] = batch.evidence[-1].id
            await self._memory.store.store(episode)

    async def learn(self, session_id: str, messages: list[Message], agent: str = "") -> list[str]:
        """새로 저장한 절차 이름. 이미 배운 구간(출처 동일)은 LLM 을 부르지 않고 건너뛴다.
        agent 는 그 세션의 에이전트다. 승인하면 그 에이전트에만 보인다.

        # ponytail: 세션 구간 학습은 출처가 구간이라 세션마다 파일이 는다, 자동 학습이 이 경로로 돌아오면 작업 종류 키로
        """
        existing = {p.name: p.source for p in self._store.list()}
        sources = set(existing.values())
        written: list[str] = []
        for span in find_spans(messages, self._min_tool_calls):
            source = source_key(session_id, span)
            if source in sources:
                continue
            draft = await self._distill(span)
            if draft is None:
                continue
            name = unique_name(draft.name, source, existing)
            self._store.save(replace(build_procedure(draft, span, source, name), agent=agent))
            existing[name] = source
            sources.add(source)
            written.append(name)
        return written


def _seen(procedure: Procedure) -> int:
    """이 절차가 이미 다룬 가장 늦은 세대. 대기 중인 개정도 센다."""
    pending = procedure.revision.generation if procedure.revision is not None else 0
    return max(procedure.generation, pending)
