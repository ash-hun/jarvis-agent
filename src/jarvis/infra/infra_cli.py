"""[infra] jarvis-infra 진입점. 설정, 클라이언트, 사고 저장소, 알림을 조립해 감시 루프와 HTTP 를 띄운다."""

import json
from typing import Any
from pathlib import Path
from functools import partial
from collections.abc import Awaitable, Callable

from jarvis.core.notify.webpush import Send, is_gone, pywebpush_sender
from jarvis.infra.push_cache import FilePushStore, sync_subscriptions
from jarvis.infra.infra_config import InfraConfig, load_config
from jarvis.infra.infra_app import EventHub, build_infra_app
from jarvis.infra.watch_service import Chore, WatchService
from jarvis.infra.backend_client import BackendClient
from jarvis.infra.incident_store import IncidentStore
from jarvis.infra.docker_client import DockerClient
from jarvis.common.logger import get_logger

logger = get_logger(__name__)


def push_notifier(store: FilePushStore, send: Send) -> Callable[[dict[str, Any]], Awaitable[None]]:
    """사고 알림을 파일에 있는 구독 전부에 보낸다. 죽은 구독은 지운다."""

    async def notify(payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        for sub in store.all():
            status = await send(sub, data)
            if is_gone(status):
                store.delete(sub.endpoint)
            elif status >= 400 or status == 0:
                logger.info(f"[Infra] web push returned {status}")

    return notify


def build(cfg: InfraConfig) -> tuple[WatchService, EventHub]:
    data_dir = Path(cfg.data_dir).expanduser()
    hub = EventHub()
    pushes = FilePushStore(data_dir / "subscriptions.json")
    notifiers: list[Callable[[dict[str, Any]], Awaitable[None]]] = [hub.publish]
    chores: list[Chore] = []
    if cfg.vapid_private_key is not None and cfg.vapid_subject:
        send = pywebpush_sender(cfg.vapid_private_key.get_secret_value(), cfg.vapid_subject)
        notifiers.append(push_notifier(pushes, send))
        logger.info("[Infra] web push on")
    if cfg.postgres_dsn:
        from jarvis.core.notify.webpush import PushStore

        chores.append(partial(_sync, PushStore(cfg.postgres_dsn), pushes))

    async def notify(payload: dict[str, Any]) -> None:
        for target in notifiers:
            await target(payload)

    token = cfg.access_key.get_secret_value() if cfg.access_key is not None else None
    service = WatchService(
        cfg,
        backend=BackendClient(cfg.backend_url, token),
        docker=DockerClient(cfg.docker_url, frozenset({cfg.backend_service})),
        store=IncidentStore(data_dir / "incidents.json"),
        notify=notify,
        chores=chores,
    )
    return service, hub


async def _sync(source: Any, target: FilePushStore) -> None:
    count = await sync_subscriptions(source, target)
    logger.debug(f"[Infra] push subscriptions synced: {count}")


def main() -> None:
    import uvicorn

    cfg = load_config()
    service, hub = build(cfg)
    token = cfg.access_key.get_secret_value() if cfg.access_key is not None else None
    app = build_infra_app(service, hub, token)
    logger.info(f"[Infra] watching {cfg.backend_service} at {cfg.backend_url} every {cfg.poll_sec:.0f}s")
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="warning")


if __name__ == "__main__":
    main()
