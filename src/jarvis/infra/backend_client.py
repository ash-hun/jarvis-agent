"""[infra] 백엔드 HTTP 클라이언트. 건강, 지표, 작업 목록을 읽고 스케줄 작업을 끈다. 모든 호출에 타임아웃."""

import httpx
from typing import Any

from jarvis.common.logger import get_logger

logger = get_logger(__name__)


class BackendClient:
    def __init__(
        self, base_url: str, token: str | None, timeout: float = 5.0, client: httpx.AsyncClient | None = None
    ) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = client if client is not None else httpx.AsyncClient(
            base_url=base_url, timeout=timeout, headers=headers
        )

    async def health(self) -> bool:
        """`GET /api/health` 가 200 이면 True. 타임아웃, 연결 실패, 5xx 는 False."""
        try:
            res = await self._client.get("/api/health")
        except httpx.HTTPError:
            return False
        return res.status_code == 200

    async def metrics(self) -> dict[str, Any] | None:
        return await self._get_json("/api/platform/metrics")

    async def jobs(self) -> list[dict[str, Any]]:
        body = await self._get_json("/api/jobs")
        jobs = body.get("jobs") if body is not None else None
        return list(jobs) if isinstance(jobs, list) else []

    async def set_task_enabled(self, name: str, enabled: bool) -> bool:
        try:
            res = await self._client.post(f"/api/schedules/{name}", json={"enabled": enabled})
        except httpx.HTTPError as exc:
            logger.info(f"[Infra] backend schedule toggle failed: {exc!r}")
            return False
        return res.status_code == 200

    async def _get_json(self, path: str) -> dict[str, Any] | None:
        try:
            res = await self._client.get(path)
            res.raise_for_status()
            data = res.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info(f"[Infra] backend {path} failed: {exc!r}")
            return None
        return data if isinstance(data, dict) else None

    async def aclose(self) -> None:
        await self._client.aclose()
