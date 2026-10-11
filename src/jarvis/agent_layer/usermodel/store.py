"""[agent_layer] 단일 사용자 모델 저장소 기본 클래스(메모리 저장)와 JSON 파일 스냅샷 저장소를 둔다."""

from __future__ import annotations

from pathlib import Path

from jarvis.agent_layer.usermodel.types import UserModel

DEFAULT_PATH = "~/.jarvis/user_model.json"


class UserModelStore:
    """단일 사용자 모델의 저장/조회 기본 클래스: 교체 가능(in_memory / jsonl). 그대로 쓰면 메모리에 담는다."""

    def __init__(self) -> None:
        self._model: UserModel | None = None

    async def get(self) -> UserModel | None:
        return self._model

    async def save(self, model: UserModel) -> None:
        self._model = model


class InMemoryUserModelStore(UserModelStore):
    """테스트·로컬용 in-memory 저장소. 동작은 기본 클래스 그대로다."""


class JsonlUserModelStore(UserModelStore):
    """단일 JSON 파일 스냅샷 저장소(레코드 1개라 append-log 불필요, 덮어쓰기)."""

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        super().__init__()
        self._path = Path(path).expanduser()
        self._loaded = False

    async def get(self) -> UserModel | None:
        if not self._loaded:
            self._loaded = True
            if self._path.exists():
                try:
                    self._model = UserModel.model_validate_json(self._path.read_text(encoding="utf-8"))
                except Exception:
                    self._model = None
        return await super().get()

    async def save(self, model: UserModel) -> None:
        await super().save(model)
        self._loaded = True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(model.model_dump_json(), encoding="utf-8")
        except OSError:
            pass  # 저장 실패는 부가 작업: 메모리 캐시는 유지
