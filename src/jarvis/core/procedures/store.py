"""[core] 절차 파일 저장소. `~/.jarvis/procedures/<name>.md` 하나가 절차 하나이고 파일명이 자연 키다."""

import os
import frontmatter
from pathlib import Path
from typing import Any, cast
from dataclasses import dataclass, replace

from jarvis.common.logger import get_logger

DEFAULT_DIR = "~/.jarvis/procedures"
STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUSES = (STATUS_DRAFT, STATUS_APPROVED)

logger = get_logger(__name__)


@dataclass(frozen=True)
class Procedure:
    name: str
    description: str
    body: str  # 절차 본문. `{{args}}` 자리에 호출 입력이 들어간다
    status: str = STATUS_DRAFT
    source: str = ""  # "<session_id>#<start>" 학습 출처. 같은 출처는 두 번 배우지 않는다
    tools: tuple[str, ...] = ()
    parameters: str = ""

    @property
    def approved(self) -> bool:
        return self.status == STATUS_APPROVED

    def render(self, args: str) -> str:
        return self.body.replace("{{args}}", args)

    def to_markdown(self) -> str:
        post = frontmatter.Post(
            self.body,
            name=self.name,
            description=self.description,
            status=self.status,
            source=self.source,
            tools=list(self.tools),
            parameters=self.parameters,
        )
        return frontmatter.dumps(post, sort_keys=False) + "\n"


def parse_procedure(text: str, fallback_name: str) -> Procedure:
    post = frontmatter.loads(text)
    meta = post.metadata
    status = str(meta.get("status", STATUS_DRAFT))
    body = post.content.strip("\n")
    return Procedure(
        name=str(meta.get("name") or fallback_name),
        description=str(meta.get("description", "")),
        body=body + "\n" if body else "",  # frontmatter 가 끝 개행을 떼므로 여기서 한 줄로 고정한다
        status=status if status in STATUSES else STATUS_DRAFT,
        source=str(meta.get("source", "")),
        # frontmatter 메타는 object 로 타입이 잡힌다. tools 는 to_markdown 이 list 로 쓴다
        tools=tuple(str(t) for t in cast(list[Any], meta.get("tools") or [])),
        parameters=str(meta.get("parameters", "")),
    )


class ProcedureStore:
    def __init__(self, root: str = DEFAULT_DIR) -> None:
        self._root = Path(root).expanduser()

    @property
    def root(self) -> Path:
        return self._root

    def _path(self, name: str) -> Path:
        return self._root / f"{name}.md"

    def list(self) -> list[Procedure]:
        if not self._root.exists():
            return []
        out: list[Procedure] = []
        for path in sorted(self._root.glob("*.md")):
            try:
                out.append(parse_procedure(path.read_text(encoding="utf-8"), path.stem))
            except Exception as exc:
                logger.info(f"[ProcedureStore] Skipping '{path.name}': {exc}")
        return out

    def get(self, name: str) -> Procedure | None:
        path = self._path(name)
        if not path.exists():
            return None
        return parse_procedure(path.read_text(encoding="utf-8"), name)

    def has_source(self, source: str) -> bool:
        return any(p.source == source for p in self.list())

    def save(self, procedure: Procedure) -> Path:
        """같은 이름은 덮어쓴다(upsert). 쓰다 죽어도 반쪽 파일이 남지 않도록 임시 파일 뒤 교체."""
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path(procedure.name)
        tmp = path.with_suffix(".md.tmp")
        tmp.write_text(procedure.to_markdown(), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def set_status(self, name: str, status: str) -> Procedure | None:
        """이미 그 상태면 파일을 다시 쓰지 않는다. 없는 이름이면 None."""
        if status not in STATUSES:
            raise ValueError(f"unknown status: {status}")
        current = self.get(name)
        if current is None:
            return None
        if current.status == status:
            return current
        updated = replace(current, status=status)
        self.save(updated)
        return updated

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if not path.exists():
            return False
        path.unlink()
        return True
