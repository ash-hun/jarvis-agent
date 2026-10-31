"""[memory] 평가 대상 어댑터. MemoryService 와 in-memory 저장소, in-memory 절차 소스로 사례를 재생하고 조회한다."""

from datetime import datetime, timedelta

from jarvis.model_layer.model_types import AssistantMessage, Message, TextContent, UserMessage
from jarvis.memory.eval.eval_schema import EpisodeFilter, RetentionCase, SetupStep
from jarvis.memory.stores.store_protocol import OUTCOME, TASK_TYPE, ItemStore
from jarvis.memory.long_term.procedural import InMemoryProcedures, Procedure
from jarvis.memory.access import MemoryPolicy, MemoryReadPolicy
from jarvis.memory.stores.in_memory import InMemoryItemStore
from jarvis.memory.scope import MAIN_AGENT, MemoryScope
from jarvis.memory.memory_service import MemoryService
from jarvis.memory.memory_types import MemoryKind

RETENTION_CONTEXT = {"session_id": "eval", "user_id": "u1", "agent_id": MAIN_AGENT}


class EvalTarget:
    """STM 3턴, EDM, PDM, 층별 권한을 가진 MemoryService. 다른 저장소는 _build 를 덮어쓴다."""

    def __init__(self) -> None:
        self._procedures = InMemoryProcedures()
        self._memory = self._build()

    def _build(self, store: ItemStore | None = None, policies: dict[str, MemoryPolicy] | None = None) -> MemoryService:
        from jarvis.memory.eval.fake_embedder import FakeEmbedder

        return MemoryService(
            store or InMemoryItemStore(), procedures=self._procedures, embedder=FakeEmbedder(), policies=policies
        )

    async def reset(self) -> None:
        self._procedures = InMemoryProcedures()
        self._memory = self._build()

    async def setup(self, step: SetupStep, scope: MemoryScope) -> None:
        if step.skill is not None:
            self._procedures.add(Procedure(name=step.skill, description=step.description, aliases=tuple(step.aliases)))
            return
        metadata = {k: v for k, v in ((TASK_TYPE, step.task_type), (OUTCOME, step.outcome)) if v is not None}
        item_id = await self._memory.remember(
            step.remember or "",
            source="eval",
            scope=scope,
            kind=step.kind,
            importance=step.importance,
            created_at=datetime.fromisoformat(step.at) if step.at else None,
            metadata=metadata,
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
        """scope 에서 query 로 떠올린 내용을 점수 순으로. kind 가 procedures 면 스킬 이름, candidates 면 정제 후보.

        사례의 정책은 team/<id>.yaml 의 memory.read 로 읽어 같은 저장소 위에 서비스를 다시 연다.
        """
        if policy:
            policies = {agent: MemoryPolicy(read=MemoryReadPolicy(**layers)) for agent, layers in policy.items()}
            self._memory = self._build(self._memory.store, policies)
        if kind == "procedures":
            return [p.name for p in self._memory.procedures(query)][:top_k]
        if kind == "candidates":
            return [c.task_type for c in await self._memory.refinement_candidates(scope)]
        if kind == "episodes" and episode_filter is not None:
            f = episode_filter
            items = await self._memory.recall_episodes(
                query, scope, task_type=f.task_type, outcome=f.outcome,
                since=datetime.fromisoformat(f.since) if f.since else None,
                until=datetime.fromisoformat(f.until) + timedelta(days=1) if f.until else None, limit=top_k,
            )
            return [i.content for i in items]
        kinds = [MemoryKind.EPISODIC] if kind == "episodes" else None
        return [i.content for i in await self._memory.recall(query, scope, kinds=kinds, limit=top_k)]

    async def converse(self, case: RetentionCase) -> list[Message]:
        """사실 턴, 채움 턴, 질문 턴을 차례로 observe 하고 질문 턴에 모델이 받는 컨텍스트를 돌려준다."""
        from jarvis.memory.eval.fake_embedder import FakeEmbedder

        memory = MemoryService(InMemoryItemStore(), embedder=FakeEmbedder(), stm_turns=case.config.stm_turns)
        history: list[Message] = []
        for user, reply in retention_turns(case):
            history.append(UserMessage(content=user, timestamp=len(history)))
            await memory.observe(history, RETENTION_CONTEXT)
            await memory.reinforce(reply, RETENTION_CONTEXT)
            history.append(AssistantMessage(content=[TextContent(text=reply)], timestamp=len(history)))
        history.append(UserMessage(content=case.question, timestamp=len(history)))
        return await memory.observe(history, RETENTION_CONTEXT)


def retention_turns(case: RetentionCase) -> list[tuple[str, str]]:
    """(사용자, 답) 쌍. 첫 턴이 사실이고 이어서 distance 개의 채움 턴이다."""
    turns = [(case.fact, "알겠습니다. 기억해 둘게요.")]
    for i in range(case.distance):
        turns.append((f"잡담 {i}: " + "가" * case.user_chars, f"답 {i}: " + "나" * case.assistant_chars))
    return turns
