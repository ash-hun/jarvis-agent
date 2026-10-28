"""[core] 목표를 id 마다 JSON 파일 하나로 두는 저장소. 같은 id 는 늘 같은 파일을 덮는다."""

import os
import json
from pathlib import Path

from jarvis.core.goals.types import Goal

GOALS_DIR = "~/.jarvis/goals"


class GoalStore:
    """쓰기는 임시 파일에 쓰고 바꿔 끼운다. 쓰다 죽어도 이전 파일이 남는다."""

    def __init__(self, root: str = GOALS_DIR) -> None:
        self._root = Path(root).expanduser()

    def _path(self, goal_id: str) -> Path:
        return self._root / f"{goal_id}.json"

    def get(self, goal_id: str) -> Goal | None:
        path = self._path(goal_id)
        if not path.exists():
            return None
        return Goal.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self, agent: str | None = None) -> list[Goal]:
        if not self._root.is_dir():
            return []
        goals = [Goal.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(self._root.glob("*.json"))]
        return [g for g in goals if agent is None or g.agent == agent]

    def save(self, goal: Goal) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        tmp = self._path(goal.id).with_suffix(".tmp")
        tmp.write_text(json.dumps(goal.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self._path(goal.id))

    def ensure(self, goal: Goal) -> tuple[Goal, bool]:
        """없으면 저장하고 (goal, True). 이미 있으면 진행 기록을 지키려고 그대로 두고 (기존, False).
        끝났거나 멈춘 목표를 다시 맡기면 다시 진행한다."""
        existing = self.get(goal.id)
        if existing is None:
            self.save(goal)
            return goal, True
        if existing.status != "active":
            existing = existing.model_copy(update={"status": "active", "updated_at": goal.updated_at})
            self.save(existing)
        return existing, False
