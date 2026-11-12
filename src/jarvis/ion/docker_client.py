"""[ion] Docker 소켓 프록시 HTTP 클라이언트. 허용한 compose 서비스만 찾고, 통계를 읽고, 재기동하거나 멈춘다."""

import json
import httpx
from typing import Any
from dataclasses import dataclass

from jarvis.common.logger import get_logger

SERVICE_LABEL = "com.docker.compose.service"
RESTART_WAIT_SEC = 10
logger = get_logger(__name__)


@dataclass(frozen=True)
class ContainerState:
    """컨테이너 하나의 지금 상태. memory 둘은 stats 를 읽었을 때만 있다."""

    id: str
    service: str
    status: str  # running | exited | restarting | paused ...
    restart_count: int
    memory_usage: int | None = None
    memory_limit: int | None = None


class DockerClient:
    """프록시에는 조회와 restart, stop 만 열려 있다. 허용 목록 밖 서비스는 부르기 전에 막는다."""

    def __init__(
        self, base_url: str, allowed: frozenset[str], timeout: float = 5.0, client: httpx.AsyncClient | None = None
    ) -> None:
        self._allowed = allowed
        self._client = client if client is not None else httpx.AsyncClient(base_url=base_url, timeout=timeout)

    def _check(self, service: str) -> None:
        if service not in self._allowed:
            raise ValueError(f"허용하지 않은 서비스: {service}")

    async def find(self, service: str) -> ContainerState | None:
        """compose 서비스 라벨로 컨테이너를 찾는다. 없거나 프록시가 답하지 않으면 None."""
        self._check(service)
        filters = json.dumps({"label": [f"{SERVICE_LABEL}={service}"]})
        try:
            listed = await self._client.get("/containers/json", params={"all": "true", "filters": filters})
            listed.raise_for_status()
            rows: list[dict[str, Any]] = listed.json()
            if not rows:
                return None
            inspect = await self._client.get(f"/containers/{rows[0]['Id']}/json")
            inspect.raise_for_status()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            logger.info(f"[Ion] docker find failed: {exc!r}")
            return None
        data: dict[str, Any] = inspect.json()
        return ContainerState(
            id=str(data.get("Id", "")),
            service=service,
            status=str((data.get("State") or {}).get("Status", "")),
            restart_count=int(data.get("RestartCount") or 0),
        )

    async def with_stats(self, state: ContainerState) -> ContainerState:
        """메모리 사용량과 한도를 한 번 읽어 붙인다. 못 읽으면 그대로 돌려준다."""
        try:
            params = {"stream": "false", "one-shot": "true"}
            res = await self._client.get(f"/containers/{state.id}/stats", params=params)
            res.raise_for_status()
            mem: dict[str, Any] = res.json().get("memory_stats") or {}
        except (httpx.HTTPError, ValueError) as exc:
            logger.info(f"[Ion] docker stats failed: {exc!r}")
            return state
        usage, limit = mem.get("usage"), mem.get("limit")
        if usage is None or limit is None:
            return state
        return ContainerState(state.id, state.service, state.status, state.restart_count, int(usage), int(limit))

    async def restart(self, service: str) -> bool:
        """재기동. 두 번 불러도 결과는 '떠 있음' 하나다."""
        return await self._post(service, "restart", {"t": str(RESTART_WAIT_SEC)})

    async def stop(self, service: str) -> bool:
        return await self._post(service, "stop", {"t": str(RESTART_WAIT_SEC)})

    async def _post(self, service: str, action: str, params: dict[str, str]) -> bool:
        state = await self.find(service)
        if state is None:
            return False
        try:
            res = await self._client.post(f"/containers/{state.id}/{action}", params=params)
        except httpx.HTTPError as exc:
            logger.info(f"[Ion] docker {action} failed: {exc!r}")
            return False
        # 304 는 이미 그 상태(멈춘 것을 또 stop)라 성공으로 본다
        return res.status_code in (204, 304)

    async def aclose(self) -> None:
        await self._client.aclose()
