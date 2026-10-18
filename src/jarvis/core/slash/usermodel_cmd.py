"""[core] 증류된 사용자 모델을 보이거나 최근 기억으로 갱신하는 /usermodel 핸들러 factory."""

from typing import TYPE_CHECKING
from collections.abc import Awaitable, Callable

if TYPE_CHECKING:
    from jarvis.agent_layer.usermodel import UserModelBuilder, UserModelStore
    from jarvis.memory.memory_service import MemoryService

Handler = Callable[[str], Awaitable[str]]

_USAGE = (
    "[UserModel] 증류된 사용자 모델 (Tier 3).\n"
    "사용법:\n"
    "  /usermodel             현재 모델 표시\n"
    "  /usermodel build       최근 기억에서 모델을 갱신"
)


def make_usermodel_handler(
    store: "UserModelStore",
    builder: "UserModelBuilder",
    memory: "MemoryService",
    build_source_limit: int = 30,
) -> Handler:
    """SlashCommandDispatcher에 등록할 /usermodel 핸들러 factory."""

    async def handle(args: str) -> str:
        sub = args.strip().lower()
        if sub == "build":
            return await _handle_build(store, builder, memory, build_source_limit)
        if sub in ("", "show", "view"):
            return await _handle_show(store)
        return _USAGE

    return handle


async def _handle_show(store: "UserModelStore") -> str:
    model = await store.get()
    if model is None or model.is_empty():
        return "[UserModel] 아직 모델이 없습니다. /usermodel build 로 생성하세요."
    lines = [f"[UserModel] (갱신: {model.source_count}개 소스 기반)"]
    if model.summary:
        lines.append(model.summary)
    lines.extend(f"  - {t}" for t in model.traits)
    return "\n".join(lines)


async def _handle_build(
    store: "UserModelStore",
    builder: "UserModelBuilder",
    memory: "MemoryService",
    limit: int,
) -> str:
    entries = await memory.recent(limit=limit)
    sources = [e.content for e in entries if e.content]
    if not sources:
        return "[UserModel] 증류할 기억이 없습니다."

    previous = await store.get()
    model = await builder.build(sources, previous=previous)
    if model is None or model.is_empty():
        return "[UserModel] 모델 생성에 실패했습니다(근거 부족 또는 파싱 실패)."

    await store.save(model)
    return await _handle_show(store)
