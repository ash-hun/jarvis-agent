from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from jarvis.agent_layer.usermodel.types import UserModel


@runtime_checkable
class UserModelStore(Protocol):
    """단일 사용자 모델의 저장/조회 — 교체 가능(in_memory / jsonl)."""

    async def get(self) -> UserModel | None: ...

    async def save(self, model: UserModel) -> None: ...


class InMemoryUserModelStore:
    """테스트·로컬용 in-memory 저장소."""

    def __init__(self) -> None:
        self._model: UserModel | None = None

    async def get(self) -> UserModel | None:
        return self._model

    async def save(self, model: UserModel) -> None:
        self._model = model


class JsonlUserModelStore:
    """단일 JSON 파일 스냅샷 저장소(레코드 1개라 append-log 불필요, 덮어쓰기)."""

    def __init__(self, path: str = "~/.jarvis/user_model.json") -> None:
        self._path = Path(path).expanduser()
        self._cache: UserModel | None = None
        self._loaded = False

    async def get(self) -> UserModel | None:
        if not self._loaded:
            self._loaded = True
            if self._path.exists():
                try:
                    self._cache = UserModel.model_validate_json(
                        self._path.read_text(encoding="utf-8")
                    )
                except Exception:
                    self._cache = None
        return self._cache

    async def save(self, model: UserModel) -> None:
        self._cache = model
        self._loaded = True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(model.model_dump_json(), encoding="utf-8")
        except OSError:
            pass  # 저장 실패는 부가 작업 — 메모리 캐시는 유지
