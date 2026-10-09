"""세션 이력에서 성공한 작업 구간을 찾아 절차 초안으로 저장한다. 같은 구간은 두 번 저장하지 않는다."""

import hashlib

from jarvis.core.procedures.detect import DEFAULT_MIN_TOOL_CALLS, TaskSpan, find_spans
from jarvis.core.procedures.distill import Distiller, ProcedureDraft
from jarvis.core.procedures.store import STATUS_DRAFT, Procedure, ProcedureStore
from jarvis.model_layer.types import Message

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
    return Procedure(
        name=name,
        description=draft.description,
        body="\n".join(lines) + "\n",
        status=STATUS_DRAFT,
        source=source,
        tools=span.tool_names,
        parameters=draft.parameters,
    )


class ProcedureLearner:
    def __init__(
        self, store: ProcedureStore, distiller: Distiller, min_tool_calls: int = DEFAULT_MIN_TOOL_CALLS
    ) -> None:
        self._store = store
        self._distill = distiller
        self._min_tool_calls = min_tool_calls

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
