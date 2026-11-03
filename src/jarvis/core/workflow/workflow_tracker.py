"""[core] 세션 이벤트(위임 도구 호출, Focus sub-agent 바쁨)에서 에이전트 사이 위임 간선을 모은다."""

from typing import Any
from dataclasses import replace
from collections import OrderedDict
from collections.abc import Callable

from jarvis.core.workflow.workflow_types import DelegationEdge, DelegationKind

# 위임 도구 이름. core/multi_agent 의 agent_<이름> 도구와 orchestrate, app 의 ask_agent
ASK_TOOL = "ask_agent"
ORCHESTRATE_TOOL = "orchestrate"
SUBAGENT_PREFIX = "agent_"
FOCUS_PREFIX = "focus-"
LABEL_CHARS = 80
# ponytail: 프로세스 메모리에 최근 위임만 둔다. 재시작하면 그래프가 빈다,
# 지난 위임까지 봐야 하면 memory 의 delegation 일화와 peer 세션 기록에서 다시 쌓는다
MAX_EDGES = 200


def delegation_of(tool_name: str, args: dict[str, Any]) -> tuple[DelegationKind, str, str] | None:
    """도구 호출이 위임이면 (종류, 받는 쪽, 맡긴 일). 위임이 아니면 None. 순수 함수."""
    if tool_name == ASK_TOOL:
        return "ask", str(args.get("agent", "")), str(args.get("message", ""))
    if tool_name == ORCHESTRATE_TOOL:
        return "orchestrate", f"{ORCHESTRATE_TOOL}:{args.get('pattern', '')}", str(args.get("task", ""))
    if tool_name.startswith(SUBAGENT_PREFIX) and len(tool_name) > len(SUBAGENT_PREFIX):
        return "subagent", tool_name[len(SUBAGENT_PREFIX):], str(args.get("task", ""))
    return None


def _clip(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= LABEL_CHARS else text[: LABEL_CHARS - 1] + "…"


class WorkflowTracker:
    """간선 id 순서를 지키는 최근 위임 MAX_EDGES 개. 같은 이벤트를 두 번 받아도 간선은 하나다."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock
        self._edges: OrderedDict[str, DelegationEdge] = OrderedDict()

    def edges(self) -> list[DelegationEdge]:
        return list(self._edges.values())

    def observe(self, session_id: str, agent_id: str, event: object) -> DelegationEdge | None:
        """세션 이벤트 하나를 반영하고 바뀐 간선을 돌려준다. 바뀐 게 없으면 None."""
        kind = getattr(event, "type", "")
        if kind == "tool_execution_start":
            found = delegation_of(str(getattr(event, "tool_name", "")), dict(getattr(event, "args", {}) or {}))
            if found is None:
                return None
            edge_kind, target, label = found
            edge_id = f"{session_id}:{getattr(event, 'tool_call_id', '')}"
            return self._open(edge_id, edge_kind, agent_id, target, label, self._time_of(event))
        if kind == "tool_execution_end":
            edge_id = f"{session_id}:{getattr(event, 'tool_call_id', '')}"
            return self._close(edge_id, not bool(getattr(event, "is_error", False)), self._time_of(event))
        if kind == "focus_panel":
            area = str(getattr(event, "area", ""))
            edge_id = f"{session_id}:{FOCUS_PREFIX}{area}"
            if getattr(event, "busy", False):
                return self._open(edge_id, "focus", agent_id, f"{FOCUS_PREFIX}{area}", area, self._clock())
            return self._close(edge_id, True, self._clock())
        return None

    def _time_of(self, event: object) -> int:
        stamp = getattr(event, "timestamp", None)
        return int(stamp) if isinstance(stamp, int) else self._clock()

    def _open(
        self, edge_id: str, kind: DelegationKind, source: str, target: str, label: str, now: int
    ) -> DelegationEdge | None:
        current = self._edges.get(edge_id)
        if current is not None and current.ended_ms is None:
            return None
        # Focus 영역은 같은 id 로 다시 바빠진다. 끝난 간선을 지우고 맨 뒤에 새로 연다
        self._edges.pop(edge_id, None)
        edge = DelegationEdge(edge_id, kind, source, target, _clip(label), now)
        self._edges[edge_id] = edge
        while len(self._edges) > MAX_EDGES:
            self._edges.popitem(last=False)
        return edge

    def _close(self, edge_id: str, ok: bool, now: int) -> DelegationEdge | None:
        current = self._edges.get(edge_id)
        if current is None or current.ended_ms is not None:
            return None
        edge = replace(current, ended_ms=now, ok=ok)
        self._edges[edge_id] = edge
        return edge
