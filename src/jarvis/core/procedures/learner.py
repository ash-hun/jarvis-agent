"""[core] 성공한 작업(세션 구간, 또는 EDM 에 쌓인 같은 종류의 성공)을 절차 초안으로 저장한다(같은 출처는 한 번만)."""

import hashlib
from dataclasses import replace
from typing import TYPE_CHECKING

from jarvis.core.procedures.detect import DEFAULT_MIN_TOOL_CALLS, TaskSpan, ToolStep, find_spans
from jarvis.core.procedures.procedures_store import STATUS_DRAFT, Procedure, ProcedureStore
from jarvis.core.procedures.distill import Distiller, ProcedureDraft
from jarvis.core.procedures.plan import valid_plan
from jarvis.model_layer.model_types import Message

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService
    from jarvis.memory.long_term.refine import Candidate
    from jarvis.memory.scope import MemoryScope

SUFFIX_LEN = 6


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


class ProcedureLearner:
    def __init__(
        self,
        store: ProcedureStore,
        distiller: Distiller,
        min_tool_calls: int = DEFAULT_MIN_TOOL_CALLS,
        memory: "MemoryService | None" = None,
    ) -> None:
        self._store = store
        self._distill = distiller
        self._min_tool_calls = min_tool_calls
        self._memory = memory

    async def refine(self, scope: "MemoryScope") -> list[str]:
        """EDM 에서 같은 작업 종류의 성공이 쌓인 것을 초안으로. 같은 세대(출처)는 LLM 을 부르지 않고 건너뛴다."""
        if self._memory is None:
            return []
        existing = {p.name: p.source for p in self._store.list()}
        sources = set(existing.values())
        written: list[str] = []
        for candidate in await self._memory.refinement_candidates(scope):
            if candidate.source in sources:
                continue
            span = episode_span(candidate)
            if span is None:
                continue
            draft = await self._distill(span)
            if draft is None:
                continue
            name = unique_name(draft.name, candidate.source, existing)
            procedure = build_procedure(draft, span, candidate.source, name)
            self._store.save(replace(procedure, agent=candidate.agent_id))
            existing[name] = candidate.source
            sources.add(candidate.source)
            written.append(name)
        return written

    async def learn(self, session_id: str, messages: list[Message]) -> list[str]:
        """새로 저장한 절차 이름. 이미 배운 구간(출처 동일)은 LLM 을 부르지 않고 건너뛴다."""
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
            self._store.save(build_procedure(draft, span, source, name))
            existing[name] = source
            sources.add(source)
            written.append(name)
        return written
