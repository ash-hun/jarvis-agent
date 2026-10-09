"""평가 대상 어댑터. 실행기는 이 프로토콜만 알고, 어느 저장소를 재는지는 주입으로 정한다."""

from datetime import datetime
from typing import Protocol

from jarvis.memory.eval.schema import SetupStep, WorkingCase
from jarvis.memory.long_term.procedural import InMemoryProcedures, Procedure
from jarvis.memory.manager import MemoryManager
from jarvis.memory.scope import MemoryScope
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.model_layer.types import Message


class EvalTarget(Protocol):
    async def reset(self) -> None: ...

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None: ...

    async def probe(self, query: str, scope: MemoryScope, top_k: int, kind: str = "recall") -> list[str]:
        """scope 에서 query 로 회상한 내용을 점수 순으로 돌려준다. kind=procedures 면 스킬 이름 목록."""
        ...


class StoreTarget:
    """jarvis.memory 의 매니저 + in-memory 저장소 + in-memory 절차 소스. 기본 평가 대상."""

    def __init__(self) -> None:
        self._procedures = InMemoryProcedures()
        self._memory = self._build()

    def _build(self) -> MemoryManager:
        from jarvis.memory.eval.fake_embedder import FakeEmbedder

        return MemoryManager(InMemoryItemStore(), procedures=self._procedures, embedder=FakeEmbedder())

    async def reset(self) -> None:
        self._procedures = InMemoryProcedures()
        self._memory = self._build()

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None:
        if step.skill is not None:
            self._procedures.add(Procedure(name=step.skill, description=step.description, aliases=tuple(step.aliases)))
            return
        item_id = await self._memory.remember(
            step.remember or "",
            source="eval",
            scope=scope,
            kind=step.kind,
            visibility=step.visibility,
            importance=step.importance,
            created_at=datetime.fromisoformat(step.at) if step.at else None,
        )
        if step.rehearsal_count:
            item = await self._memory.get(item_id)
            if item is not None:
                item.rehearsal_count = step.rehearsal_count
                await self._memory.store.store(item)

    async def probe(self, query: str, scope: MemoryScope, top_k: int, kind: str = "recall") -> list[str]:
        if kind == "procedures":
            return [p.name for p in self._memory.procedures(query)][:top_k]
        return [i.content for i in await self._memory.recall(query, scope, limit=top_k)]


TARGETS = {"store": StoreTarget}


class WorkingTarget:
    """MemoryManager.observe 를 턴 단위로 돌리며 요약기 호출 수와 컨텍스트를 기록한다.

    요약기는 LLM 대신 결정론 스텁(호출 수를 센다). 저장소는 in-memory 이고 사례 안에서 공유되므로
    rebuild_between_turns 로 매니저를 새로 만들어도 요약이 살아 있어야 한다.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def run_case(self, case: WorkingCase) -> tuple[list[int], list[list[Message]]]:
        from jarvis.memory.stores.in_memory import InMemoryItemStore
        from jarvis.memory.working.in_memory import InMemoryWorkingStore

        store, working = InMemoryItemStore(), InMemoryWorkingStore()

        async def stub_summarizer(messages: list[Message], prior: str | None) -> str:
            self.calls += 1
            return f"요약: {len(messages)}개 메시지" + (f" (이전: {prior})" if prior else "")

        def build() -> MemoryManager:
            c = case.config
            return MemoryManager(
                store, working, summarizer=stub_summarizer,
                threshold_chars=c.threshold_chars, keep_recent=c.keep_recent, window_size=c.window_size,
            )

        manager = build()
        history: list[Message] = []
        calls_per_turn: list[int] = []
        contexts: list[list[Message]] = []
        context = {"session_id": "eval", "user_id": "u1", "agent_id": "main"}
        for turn in case.turns:
            if case.config.rebuild_between_turns:
                manager = build()
            history.extend(_turn_messages(len(history), turn.messages, turn.chars))
            before = self.calls
            out = await manager.observe(history, context)
            calls_per_turn.append(self.calls - before)
            contexts.append(out)
        return calls_per_turn, contexts


def _turn_messages(offset: int, count: int, chars: int) -> list[Message]:
    from jarvis.model_layer.types import AssistantMessage, TextContent, UserMessage

    out: list[Message] = []
    for i in range(offset, offset + count):
        text = f"m{i} " + "x" * chars
        if i % 2 == 0:
            out.append(UserMessage(content=text, timestamp=i))
        else:
            out.append(AssistantMessage(content=[TextContent(text=text)], timestamp=i))
    return out
