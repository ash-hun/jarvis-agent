"""[scripts] 목표 저장소의 맡기기, 읽기, 목록 시간과 두 번 맡겨도 하나인지를 잰다. 임시 디렉터리에서 돈다."""

import json
import time
import tempfile
import statistics

from jarvis.core.goals.goals_types import Goal, goal_key
from jarvis.core.goals.goals_store import GoalStore

COUNTS = (10, 100, 1000)


def bench(count: int) -> dict[str, float | int]:
    with tempfile.TemporaryDirectory() as root:
        store = GoalStore(root)
        goals = [Goal(id=goal_key("karen", f"목표 {i}"), agent="karen", text=f"목표 {i}") for i in range(count)]
        ensure_ms = []
        for g in goals:
            start = time.perf_counter()
            store.ensure(g)
            ensure_ms.append((time.perf_counter() - start) * 1000)
        # 같은 목표를 다시 맡겨도 늘지 않아야 한다
        for g in goals:
            store.ensure(g)
        start = time.perf_counter()
        listed = store.list("karen")
        list_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        store.get(goals[-1].id)
        get_ms = (time.perf_counter() - start) * 1000
        return {
            "goals": count,
            "after_second_ensure": len(listed),
            "ensure_p50_ms": round(statistics.median(ensure_ms), 3),
            "ensure_max_ms": round(max(ensure_ms), 3),
            "get_ms": round(get_ms, 3),
            "list_ms": round(list_ms, 1),
        }


if __name__ == "__main__":
    for row in (bench(n) for n in COUNTS):
        print(json.dumps(row, ensure_ascii=False))
