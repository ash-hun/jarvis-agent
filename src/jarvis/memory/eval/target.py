"""[memory] 평가 대상 어댑터로, 실행기는 EvalTarget 만 알고 어느 저장소를 재는지는 주입으로 정한다."""

from datetime import datetime

from jarvis.memory.eval.schema import EpisodeFilter, RetentionCase, SetupStep, WorkingCase
from jarvis.model_layer.types import AssistantMessage, Message, TextContent, UserMessage
from jarvis.memory.long_term.procedural import InMemoryProcedures, Procedure
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.scope import MAIN_AGENT, MemoryScope
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.types import MemoryKind

RETENTION_CONTEXT = {"session_id": "eval", "user_id": "u1", "agent_id": MAIN_AGENT}


class EvalTarget:
    """평가 대상. 기본은 MemoryService + in-memory 저장소 + in-memory 절차 소스, 다른 저장소는 _build 를 덮어쓴다."""

    def __init__(self) -> None:
        self._procedures = InMemoryProcedures()
        self._memory = self._build()

    def _build(self) -> MemoryService:
        from jarvis.memory.eval.fake_embedder import FakeEmbedder

        return MemoryService(InMemoryItemStore(), procedures=self._procedures, embedder=FakeEmbedder())

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

    async def probe(
        self,
        query: str,
        scope: MemoryScope,
        top_k: int,
        kind: str = "recall",
        episode_filter: EpisodeFilter | None = None,
        policy: dict[str, dict[str, list[str]]] | None = None,
    ) -> list[str]:
        """scope 에서 query 로 회상한 내용을 점수 순으로 돌려준다. kind=procedures 면 스킬 이름 목록.

        기존 저장소는 일화 메타데이터와 층별 권한이 없어 episode_filter 와 policy 를 무시한다. 재설계 비교의 기준선이다.
        """
        if kind == "procedures":
            return [p.name for p in self._memory.procedures(query)][:top_k]
        if kind == "candidates":
            return []  # 기존 구조에는 일화에서 절차를 정제하는 경로가 없다
        kinds = [MemoryKind.EPISODIC] if kind == "episodes" else None
        return [i.content for i in await self._memory.recall(query, scope, kinds=kinds, limit=top_k)]

    async def converse(self, case: RetentionCase) -> list[Message]:
        """사실 턴, 채움 턴, 질문 턴을 차례로 observe 하고 질문 턴에 모델이 받는 컨텍스트를 돌려준다."""
        from jarvis.memory.eval.faithfulness import extractive_summarizer
        from jarvis.memory.eval.fake_embedder import FakeEmbedder

        c = case.config
        memory = MemoryService(
            InMemoryItemStore(), summarizer=extractive_summarizer(), embedder=FakeEmbedder(),
            threshold_chars=c.threshold_chars, keep_recent=c.keep_recent, window_size=c.window_size,
        )
        history: list[Message] = []
        for user, reply in retention_turns(case):
            history.append(UserMessage(content=user, timestamp=len(history)))
            await memory.observe(history, RETENTION_CONTEXT)
            await memory.reinforce(reply, RETENTION_CONTEXT)
            history.append(AssistantMessage(content=[TextContent(text=reply)], timestamp=len(history)))
        history.append(UserMessage(content=case.question, timestamp=len(history)))
        return await memory.observe(history, RETENTION_CONTEXT)


class StoreTarget(EvalTarget):
    """jarvis.memory 의 서비스 + in-memory 저장소 + in-memory 절차 소스. 기본 평가 대상."""


class LayeredTarget(EvalTarget):
    """재설계(STM 3턴, EDM, PDM, 층별 권한) 대상. PR 마다 해당 메서드를 덮어쓰고, 덮기 전에는 기존과 같다."""


TARGETS: dict[str, type[EvalTarget]] = {"store": StoreTarget, "layered": LayeredTarget}


def retention_turns(case: RetentionCase) -> list[tuple[str, str]]:
    """(사용자, 답) 쌍. 첫 턴이 사실이고 이어서 distance 개의 채움 턴이다."""
    turns = [(case.fact, "알겠습니다. 기억해 둘게요.")]
    for i in range(case.distance):
        turns.append((f"잡담 {i}: " + "가" * case.user_chars, f"답 {i}: " + "나" * case.assistant_chars))
    return turns


class WorkingTarget:
    """MemoryService.observe 를 턴 단위로 돌리며 요약기 호출 수와 컨텍스트를 기록한다.

    요약기는 LLM 대신 결정론 스텁(호출 수를 센다). 저장소는 in-memory 이고 사례 안에서 공유되므로
    rebuild_between_turns 로 서비스를 새로 만들어도 요약이 살아 있어야 한다.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def run_case(self, case: WorkingCase) -> tuple[list[int], list[list[Message]]]:
        from jarvis.memory.working.in_memory import InMemoryWorkingStore
        from jarvis.memory.stores.in_memory import InMemoryItemStore

        store, working = InMemoryItemStore(), InMemoryWorkingStore()

        async def stub_summarizer(messages: list[Message], prior: str | None) -> str:
            self.calls += 1
            return f"요약: {len(messages)}개 메시지" + (f" (이전: {prior})" if prior else "")

        def build() -> MemoryService:
            c = case.config
            return MemoryService(
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
    out: list[Message] = []
    for i in range(offset, offset + count):
        text = f"m{i} " + "x" * chars
        if i % 2 == 0:
            out.append(UserMessage(content=text, timestamp=i))
        else:
            out.append(AssistantMessage(content=[TextContent(text=text)], timestamp=i))
    return out
