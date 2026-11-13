"""[ion] 사고 기록. JSON 파일 하나에 사고 id 로 두고, 같은 id 를 두 번 열어도 하나다."""

import json
from pathlib import Path
from dataclasses import asdict, dataclass, replace

Response = str  # restart | pause | ignore


@dataclass(frozen=True)
class Incident:
    """사고 하나. notified_ms 가 있으면 알렸고, closed_ms 가 있으면 신호가 사라져 닫힌 것이다."""

    id: str
    kind: str
    target: str
    detail: str
    opened_ms: int
    notified_ms: int | None = None
    response: Response | None = None
    responded_ms: int | None = None
    action_result: str = ""  # 답에 따라 한 행동의 결과 한 줄
    closed_ms: int | None = None

    @property
    def open(self) -> bool:
        return self.closed_ms is None


class IncidentStore:
    """사고 id → Incident. 바뀔 때마다 파일에 통째로 쓴다. 파일이 없으면 빈 것으로 시작한다."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._incidents: dict[str, Incident] = self._load()

    def get(self, incident_id: str) -> Incident | None:
        return self._incidents.get(incident_id)

    def open_incidents(self) -> list[Incident]:
        """닫히지 않은 사고. id 순."""
        return [self._incidents[k] for k in sorted(self._incidents) if self._incidents[k].open]

    def recent(self, limit: int) -> list[Incident]:
        """열린 것과 닫힌 것을 함께, 연 시각이 늦은 순으로 limit 건."""
        rows = sorted(self._incidents.values(), key=lambda i: (i.opened_ms, i.id), reverse=True)
        return rows[:max(0, limit)]

    def open(self, incident: Incident) -> tuple[Incident, bool]:
        """사고를 연다. 같은 id 가 있으면 그것을 돌려주고 새로 만들지 않는다(둘째 값 False)."""
        existing = self._incidents.get(incident.id)
        if existing is not None:
            return existing, False
        self._incidents[incident.id] = incident
        self._save()
        return incident, True

    def mark_notified(self, incident_id: str, at_ms: int) -> Incident | None:
        """알린 시각을 적는다. 이미 적혀 있으면 그대로 둔다(두 번 알리지 않는다)."""
        return self._update(incident_id, lambda i: i if i.notified_ms is not None else replace(i, notified_ms=at_ms))

    def respond(self, incident_id: str, response: Response, at_ms: int, result: str = "") -> Incident | None:
        """사용자의 답과 그에 따른 행동 결과를 적는다. 답을 두 번 받아도 처음 것이 남는다."""
        return self._update(
            incident_id,
            lambda i: i if i.response is not None
            else replace(i, response=response, responded_ms=at_ms, action_result=result),
        )

    def close(self, incident_id: str, at_ms: int) -> Incident | None:
        return self._update(incident_id, lambda i: i if i.closed_ms is not None else replace(i, closed_ms=at_ms))

    def _update(self, incident_id: str, change: object) -> Incident | None:
        current = self._incidents.get(incident_id)
        if current is None:
            return None
        assert callable(change)
        updated: Incident = change(current)
        if updated != current:
            self._incidents[incident_id] = updated
            self._save()
        return updated

    def _load(self) -> dict[str, Incident]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text(encoding="utf-8") or "{}")
        return {k: Incident(**v) for k, v in data.items()}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: asdict(v) for k, v in sorted(self._incidents.items())}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self._path)
