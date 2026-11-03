"""[core] ProactiveBench 시험 세트 장면을 성찰 요청과 3단 라벨로 바꾸고 표본을 층화해 고른다."""

# 출처: thunlp/ProactiveAgent(Apache-2.0) dataset/test_data/*.json, splits.json. 시험 세트는 실제 사용자 활동에서
# 모은 12 개 흐름, 233 사건(코딩 6 개, 글쓰기 6 개)이다. 논문 표 1 의 일상(Daily Life)은 학습 세트에만 있다.
# 사건 하나: {"observation": {"time", "event"}, "agent_response": {"candidate_task": [...]}, "task_status": bool}.
# candidate_task 는 여러 모델이 낸 제안 다섯 개로, 사람 셋이 받아들이거나 모두 거절(reject all)했다. 제안이 빈
# 사건은 사람이 판정하지 않은 사건이다(흐름마다 거의 한 칸씩 번갈아 비어 있다).
#
# 라벨 대응(원래 라벨 → 3단 라벨):
#   task_status 참                      → must      (사람이 도움이 필요하다고 보고 제안을 받아들였다)
#   task_status 거짓, 제안 있음          → must_not  (제안을 보고 모두 거절했다. 도움이 필요 없었다)
#   task_status 거짓, 제안 없음          → can       (사람 판정이 없다. recall 과 오경보에서 뺀다)
# 공식 채점은 공개되지 않은 보상 모델이 제안마다 수락을 판정한다. 여기서는 그 대신 사람 라벨로 말할지만 잰다.

import random
from typing import Any
from datetime import datetime
from pydantic import BaseModel
from collections.abc import Sequence

from jarvis.core.proactive.eval.eval_schema import CaseLabel, Situation
from jarvis.agent_layer.thought.thought_types import ThoughtRequest
from jarvis.core.proactive.eval.runner import to_request

SCORED_LABELS: tuple[CaseLabel, ...] = ("must", "must_not")


class BenchEvent(BaseModel):
    """시험 세트의 사건 하나. scene 은 파일 이름(code_11), index 는 흐름 안 순서다."""

    scene: str
    category: str
    index: int
    label: CaseLabel
    events: list[str]  # 흐름 처음부터 이 사건까지, 시간 오름차순. 마지막이 지금 일어난 사건

    @property
    def id(self) -> str:
        return f"{self.scene}#{self.index}"


def to_label(task_status: bool, candidates: Sequence[str]) -> CaseLabel:
    if task_status:
        return "must"
    return "must_not" if any(c.strip() for c in candidates) else "can"


def format_events(observations: Sequence[dict[str, Any]]) -> list[str]:
    """사건을 지금(마지막 사건) 기준 몇 초 전인지와 영문 원문으로 적는다. 원본 시각은 2024 년 epoch 라 그대로 두면
    엔진의 고정 시계(2026 년)와 어긋난다."""
    times = [float(o["time"]) for o in observations]
    last = times[-1] if times else 0.0
    out: list[str] = []
    for t, o in zip(times, observations, strict=True):
        ago = round(last - t)
        out.append(f"[{'now' if ago <= 0 else f'{ago}s ago'}] {str(o['event']).strip()}")
    return out


def scene_events(scene: str, trace: Sequence[dict[str, Any]]) -> list[BenchEvent]:
    """흐름 파일 하나를 사건마다 하나씩, 그 사건까지의 이벤트 로그와 라벨로 편다."""
    category = scene.split("_")[0]
    observations = [e["observation"] for e in trace]
    return [
        BenchEvent(
            scene=scene,
            category=category,
            index=i,
            label=to_label(bool(e.get("task_status")), e.get("agent_response", {}).get("candidate_task") or []),
            events=format_events(observations[: i + 1]),
        )
        for i, e in enumerate(trace)
    ]


def to_situation(event: BenchEvent) -> Situation:
    """최근 대화와 열린 약속은 비운다. 공식 실행도 대화 없이 이벤트 로그만 준다."""
    return Situation(external_events=event.events)


def to_thought_request(event: BenchEvent, now: datetime) -> ThoughtRequest:
    return to_request(to_situation(event), now)


def stratified_sample(events: Sequence[BenchEvent], limit: int, seed: int) -> list[BenchEvent]:
    """채점하는 라벨(must, must_not)만 (장면 종류, 라벨) 층에 비례해 고른다. 몫은 최대 나머지 방식, 층 안은 seed 로
    섞는다. 모델과 무관해 같은 seed 면 모든 모델이 같은 목록을 쓴다. 결과는 id 순."""
    pool = sorted((e for e in events if e.label in SCORED_LABELS), key=lambda e: e.id)
    strata: dict[tuple[str, str], list[BenchEvent]] = {}
    for e in pool:
        strata.setdefault((e.category, e.label), []).append(e)
    n = min(limit, len(pool))
    if n <= 0:
        return []
    keys = sorted(strata)
    exact = {k: n * len(strata[k]) / len(pool) for k in keys}
    quota = {k: int(exact[k]) for k in keys}
    for k in sorted(keys, key=lambda k: (-(exact[k] - quota[k]), k))[: n - sum(quota.values())]:
        quota[k] += 1
    rng = random.Random(seed)
    picked: list[BenchEvent] = []
    for k in keys:
        members = list(strata[k])
        rng.shuffle(members)
        picked += members[: quota[k]]
    return sorted(picked, key=lambda e: e.id)


def vertex_score(recall: float | None, false_alarm: float | None) -> float:
    """(must recall + (1 − must_not 오경보율)) / 2 × 100. 한쪽 라벨이 없으면 있는 쪽만 쓴다."""
    parts = [x for x in (recall, None if false_alarm is None else 1 - false_alarm) if x is not None]
    return round(100 * sum(parts) / len(parts), 2) if parts else 0.0
