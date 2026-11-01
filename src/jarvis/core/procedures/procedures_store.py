"""[core] 절차 파일 저장소. `~/.jarvis/procedures/<name>.md` 하나가 절차 하나이고 파일명이 자연 키다."""

import os
import frontmatter
from pathlib import Path
from typing import Any, cast
from dataclasses import dataclass, replace

from jarvis.core.procedures.plan import PlanStep, parse_plan
from jarvis.common.logger import get_logger

DEFAULT_DIR = "~/.jarvis/procedures"
ARCHIVE_DIR = ".archive"  # 수렴하며 밀려난 옛 세대 파일. glob("*.md") 에 걸리지 않아 도구로 오르지 않는다
STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUSES = (STATUS_DRAFT, STATUS_APPROVED)
KIND_PROCEDURE = "procedure"
# 실패 반성이 낸 작업 패턴 초안. 승인하면 메모리의 작업 패턴으로 옮기고 파일은 지운다
KIND_TASK_PATTERN = "task_pattern"
KINDS = (KIND_PROCEDURE, KIND_TASK_PATTERN)

logger = get_logger(__name__)


@dataclass(frozen=True)
class Procedure:
    name: str
    description: str
    body: str  # 절차 본문. `{{args}}` 자리에 호출 입력이 들어간다
    status: str = STATUS_DRAFT
    # 학습 출처. EDM 정제는 "edm:<에이전트>:<작업 종류>", 세션 학습은 "<session_id>#<start>". 같은 출처는 파일 하나다
    source: str = ""
    tools: tuple[str, ...] = ()
    parameters: str = ""
    # 입력만 채우면 그대로 돌릴 수 있는 도구 호출 순서. 비면 본문(레시피)만 돌려준다
    inputs: tuple[str, ...] = ()
    plan: tuple[PlanStep, ...] = ()
    # 절차를 배운 에이전트. 승인하면 이 에이전트의 세션에만 도구와 스킬로 보인다. 비면 main 이다
    agent: str = ""
    # 마지막으로 배우거나 검토한 성공 세대. 이 세대까지는 LLM 을 다시 부르지 않는다
    generation: int = 0
    # 승인된 절차의 개정 초안. 승인하면 본문을 이것으로 바꾼다. 한 칸이라 새 개정은 옛 개정을 덮는다
    revision: "Procedure | None" = None
    kind: str = KIND_PROCEDURE
    keywords: tuple[str, ...] = ()  # 작업 패턴 초안만 쓴다

    @property
    def approved(self) -> bool:
        return self.status == STATUS_APPROVED

    def render(self, args: str) -> str:
        return self.body.replace("{{args}}", args)

    def to_markdown(self) -> str:
        post = frontmatter.Post(self.body, **self._meta())
        return frontmatter.dumps(post, sort_keys=False) + "\n"

    def _meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "source": self.source,
            "tools": list(self.tools),
            "parameters": self.parameters,
        }
        if self.agent:
            meta["agent"] = self.agent
        if self.plan:
            meta["inputs"] = list(self.inputs)
            meta["plan"] = [{"tool": step.tool, "args": step.args} for step in self.plan]
        if self.generation:
            meta["generation"] = self.generation
        if self.kind != KIND_PROCEDURE:
            meta["kind"] = self.kind
        if self.keywords:
            meta["keywords"] = list(self.keywords)
        if self.revision is not None:
            meta["revision"] = {**self.revision._meta(), "body": self.revision.body}
        return meta


def parse_procedure(text: str, fallback_name: str) -> Procedure:
    post = frontmatter.loads(text)
    body = post.content.strip("\n")
    # frontmatter 가 끝 개행을 떼므로 여기서 한 줄로 고정한다
    return _from_meta(post.metadata, body + "\n" if body else "", fallback_name)


def _from_meta(meta: dict[str, Any], body: str, fallback_name: str) -> Procedure:
    status = str(meta.get("status", STATUS_DRAFT))
    kind = str(meta.get("kind", KIND_PROCEDURE))
    raw_revision = meta.get("revision")
    revision = None
    if isinstance(raw_revision, dict):
        revision = _from_meta(raw_revision, str(raw_revision.get("body", "")), fallback_name)
    return Procedure(
        name=str(meta.get("name") or fallback_name),
        description=str(meta.get("description", "")),
        body=body,
        status=status if status in STATUSES else STATUS_DRAFT,
        source=str(meta.get("source", "")),
        # frontmatter 메타는 object 로 타입이 잡힌다. tools 는 to_markdown 이 list 로 쓴다
        tools=tuple(str(t) for t in cast(list[Any], meta.get("tools") or [])),
        parameters=str(meta.get("parameters", "")),
        inputs=tuple(str(i) for i in cast(list[Any], meta.get("inputs") or [])),
        plan=parse_plan(meta.get("plan")),
        agent=str(meta.get("agent", "")),
        generation=int(meta.get("generation") or 0),
        revision=revision,
        kind=kind if kind in KINDS else KIND_PROCEDURE,
        keywords=tuple(str(k) for k in cast(list[Any], meta.get("keywords") or [])),
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

    def approve(self, name: str) -> Procedure | None:
        """개정 초안이 있으면 본문을 개정으로 바꾸고, 없으면 상태만 승인으로. 두 번 불러도 같은 파일이다."""
        current = self.get(name)
        if current is None:
            return None
        if current.revision is None:
            return self.set_status(name, STATUS_APPROVED)
        updated = adopt_revision(current)
        self.save(updated)
        return updated

    def drop_revision(self, name: str) -> Procedure | None:
        """개정 초안만 버린다. 그 세대는 검토한 것으로 남겨 같은 세대로 다시 증류하지 않는다."""
        current = self.get(name)
        if current is None or current.revision is None:
            return None
        updated = replace(current, revision=None, generation=max(current.generation, current.revision.generation))
        self.save(updated)
        return updated

    def archive(self, name: str) -> Path | None:
        """파일을 지우지 않고 보관 폴더로 옮긴다. 같은 이름이 이미 보관돼 있으면 번호를 붙인다."""
        path = self._path(name)
        if not path.exists():
            return None
        folder = self._root / ARCHIVE_DIR
        folder.mkdir(parents=True, exist_ok=True)
        target, n = folder / path.name, 1
        while target.exists():
            target, n = folder / f"{name}.{n}.md", n + 1
        os.replace(path, target)
        return target

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if not path.exists():
            return False
        path.unlink()
        return True


def adopt_revision(current: Procedure) -> Procedure:
    """개정의 본문과 계획을 쓰되 이름, 출처, 에이전트는 지금 절차 것을 지킨다(도구 이름이 바뀌지 않게)."""
    assert current.revision is not None
    rev = current.revision
    return replace(
        rev, name=current.name, source=current.source, agent=current.agent, status=STATUS_APPROVED,
        kind=current.kind, revision=None, generation=max(current.generation, rev.generation),
    )
