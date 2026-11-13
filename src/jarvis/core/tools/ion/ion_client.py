"""[client] 백엔드 안의 Ion 도구가 Ion 컨테이너 HTTP(/ion/*)를 부른다. 주소는 설정 하나뿐이고 모든 호출에 타임아웃."""

import httpx
from typing import Any


class IonUnavailable(Exception):
    """Ion 에 닿지 않거나 Ion 이 오류로 답했다. 도구는 이 메시지를 오류 결과로 돌려준다."""


class IonClient:
    def __init__(
        self, base_url: str, token: str | None, timeout: float = 5.0, client: httpx.AsyncClient | None = None
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client if client is not None else httpx.AsyncClient(
            base_url=base_url, timeout=timeout, headers=headers
        )

    async def status(self) -> dict[str, Any]:
        return await self._json("GET", "/ion/status")

    async def incidents(self, closed: bool = True, limit: int = 20) -> list[dict[str, Any]]:
        body = await self._json("GET", "/ion/incidents", params={"closed": int(closed), "limit": limit})
        rows = body.get("incidents")
        return list(rows) if isinstance(rows, list) else []

    async def respond(self, incident_id: str, action: str) -> dict[str, Any] | None:
        """사고에 답한다. 모르는 사고면 None. 같은 답을 두 번 보내도 Ion 은 처음 것만 행동으로 옮긴다."""
        try:
            body = await self._json("POST", f"/ion/incidents/{incident_id}/respond", json={"action": action})
        except IonUnavailable as exc:
            if "404" in str(exc):
                return None
            raise
        incident = body.get("incident")
        return dict(incident) if isinstance(incident, dict) else None

    async def restart(self) -> bool:
        """사고 없이 백엔드를 재기동한다. 부를 때마다 한 번."""
        try:
            body = await self._json("POST", "/ion/restart")
        except IonUnavailable as exc:
            if "502" in str(exc):
                return False
            raise
        return bool(body.get("ok"))

    async def logs(self, since_ms: int | None, until_ms: int | None, lines: int) -> str:
        params: dict[str, Any] = {"lines": lines}
        if since_ms is not None:
            params["since_ms"] = since_ms
        if until_ms is not None:
            params["until_ms"] = until_ms
        body = await self._json("GET", "/ion/logs", params=params)
        return str(body.get("text") or "")

    async def _json(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            res = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise IonUnavailable(f"Ion 에 닿지 않는다: {exc!r}") from exc
        if res.status_code >= 400:
            raise IonUnavailable(f"Ion 이 {res.status_code} 로 답했다: {res.text[:200]}")
        try:
            data = res.json()
        except ValueError as exc:
            raise IonUnavailable("Ion 의 답이 JSON 이 아니다") from exc
        return dict(data) if isinstance(data, dict) else {}
