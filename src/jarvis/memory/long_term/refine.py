"""[memory] 같은 작업 종류의 턴 일화에서 절차로 정제할 성공 묶음과 반성할 실패 묶음을 고르는 순수 함수."""

from datetime import datetime
from dataclasses import dataclass
from collections.abc import Iterable

from jarvis.memory.stores.store_protocol import OUTCOME, TASK_TYPE
from jarvis.memory.memory_types import MemoryItem, MemoryKind
from jarvis.memory.scope import MemoryScope

MIN_SUCCESSES = 3  # 한 번 성공은 우연일 수 있다. 같은 종류가 이만큼 성공해야 절차로 본다
CHAT_TASK = "chat"  # 도구를 부르지 않은 턴. 따라 할 절차가 없고, 실패는 모델 오류라 고칠 범위가 없다
SUCCESS = "success"
FAILURE = "failure"
# 반성한 실패 일화에 남기는 결과(accepted | no_change | refused | blocked). 표시된 일화는 다시 반성하지 않는다
REFLECTED = "reflected"
REFLECT_BATCH = "reflect_batch"  # 한 번에 반성한 묶음이 공유하는 키(묶음의 가장 최근 일화 id)
REFUSED = "refused"
BLOCKED = "blocked"
OVERFLOW = "overflow"  # 턴 일화 metadata: 도구 반복 예산을 다 써서 정리하고 이어간 턴(EMMA-3)
MAX_BATCH = 3  # 반성 한 번에 보여 주는 실패 수. 프롬프트 길이를 묶는다
MAX_REFUSALS = 2  # 같은 작업 종류의 반성이 이만큼 잇달아 거부되면 새 성공이 올 때까지 멈춘다


@dataclass(frozen=True)
class Candidate:
    agent_id: str
    task_type: str
    evidence: tuple[MemoryItem, ...]  # 오래된 것부터

    @property
    def generation(self) -> int:
        """성공이 MIN_SUCCESSES 개 쌓일 때마다 한 세대. 같은 세대는 다시 정제하지 않는다."""
        return len(self.evidence) // MIN_SUCCESSES

    @property
    def source(self) -> str:
        """절차 저장소의 자연 키. 세대를 넣지 않아 (에이전트, 작업 종류) 하나에 절차 파일 하나다."""
        return procedure_source(self.agent_id, self.task_type)


@dataclass(frozen=True)
class FailureBatch:
    agent_id: str
    task_type: str
    evidence: tuple[MemoryItem, ...]  # 아직 반성하지 않은 실패, 오래된 것부터
    blocked: bool = False  # 직전 반성이 MAX_REFUSALS 번 잇달아 거부됐다. LLM 을 부르지 않는다

    @property
    def source(self) -> str:
        return procedure_source(self.agent_id, self.task_type)


def procedure_source(agent_id: str, task_type: str) -> str:
    return f"edm:{agent_id}:{task_type}"


def candidates(episodes: Iterable[MemoryItem], scope: MemoryScope) -> list[Candidate]:
    """scope 의 에이전트가 직접 겪은 성공 일화만 센다. 다른 에이전트의 일화는 읽을 수 있어도 섞지 않는다."""
    groups = _own_by_task(episodes, scope, SUCCESS)
    return [
        Candidate(scope.agent_id, task, tuple(sorted(items, key=_at)))
        for task, items in sorted(groups.items())
        if len(items) >= MIN_SUCCESSES
    ]


def failures(episodes: Iterable[MemoryItem], scope: MemoryScope) -> list[FailureBatch]:
    """작업 종류마다 아직 반성하지 않은 최근 실패 MAX_BATCH 개. 남은 옛 실패는 다음 틱에 다른 묶음이 된다."""
    items = list(episodes)
    failed = _own_by_task(items, scope, FAILURE)
    succeeded = _own_by_task(items, scope, SUCCESS)
    out: list[FailureBatch] = []
    for task, group in sorted(failed.items()):
        pending = sorted((i for i in group if not i.metadata.get(REFLECTED)), key=_at)[-MAX_BATCH:]
        if pending:
            blocked = refusal_streak(group, succeeded.get(task, [])) >= MAX_REFUSALS
            out.append(FailureBatch(scope.agent_id, task, tuple(pending), blocked))
    return out


def refusal_streak(failed: list[MemoryItem], succeeded: list[MemoryItem]) -> int:
    """가장 최근 묶음부터 잇달아 거부된 반성 수. 마지막 거부 뒤에 같은 종류가 성공했으면 0 이다."""
    batches: dict[str, tuple[tuple[datetime, str], str]] = {}
    for item in failed:
        result = item.metadata.get(REFLECTED)
        if not result or result == BLOCKED:
            continue
        key = str(item.metadata.get(REFLECT_BATCH) or item.id)
        at = max(_at(item), batches[key][0]) if key in batches else _at(item)
        batches[key] = (at, str(result))
    streak, last_refused = 0, None
    for at, result in sorted(batches.values(), reverse=True):
        if result != REFUSED:
            break
        streak += 1
        last_refused = last_refused or at
    if last_refused is not None and any(_at(s) > last_refused for s in succeeded):
        return 0
    return streak


def _own_by_task(episodes: Iterable[MemoryItem], scope: MemoryScope, outcome: str) -> dict[str, list[MemoryItem]]:
    groups: dict[str, list[MemoryItem]] = {}
    for item in episodes:
        task = item.metadata.get(TASK_TYPE)
        if (
            item.kind is MemoryKind.EPISODIC
            and item.scope.user_id == scope.user_id
            and item.scope.agent_id == scope.agent_id
            and task and task != CHAT_TASK
            and item.metadata.get(OUTCOME) == outcome
        ):
            groups.setdefault(str(task), []).append(item)
    return groups


def _at(item: MemoryItem) -> tuple[datetime, str]:
    return (item.occurred_at or item.created_at, item.id)
