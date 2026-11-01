"""[core] Markdown/YAML 스킬(명령 매크로)을 읽어 이름과 별칭으로 찾고 '/스킬 인자' 입력을 프롬프트로 확장한다."""

import yaml
import frontmatter
from typing import Any
from pathlib import Path

from jarvis.common.logger import get_logger

logger = get_logger(__name__)


class Skill:
    def __init__(self, name: str, description: str, aliases: list[str], content: str, metadata: dict[str, Any]) -> None:
        self.name = name
        self.description = description
        self.aliases = aliases
        self.content = content
        self.metadata = metadata

    def visible_to(self, agent: str | None) -> bool:
        """승인된 절차의 스킬은 그 절차를 배운 에이전트에게만 보인다. agent 가 None 이면 거르지 않는다."""
        owner = self.metadata.get("agent") if self.metadata.get("procedure") else None
        return agent is None or owner is None or owner == agent


class SkillRegistry:
    """Markdown/YAML 기반 스킬(명령 매크로) 레지스트리. Pi: skills.ts + prompt-templates.ts 패턴."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._aliases: dict[str, str] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        for alias in skill.aliases:
            self._aliases[alias] = skill.name

    def unregister(self, name: str) -> None:
        skill = self._skills.pop(name, None)
        if skill:
            for alias in skill.aliases:
                self._aliases.pop(alias, None)

    def get(self, name_or_alias: str, agent: str | None = None) -> Skill | None:
        """agent 를 주면 그 에이전트에게 보이는 스킬만 찾는다."""
        name = self._aliases.get(name_or_alias, name_or_alias)
        skill = self._skills.get(name)
        return skill if skill is not None and skill.visible_to(agent) else None

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def expand(self, input_text: str, agent: str | None = None) -> str:
        """'/skill_name args' 형태의 입력을 스킬 내용으로 확장. agent 에게 보이지 않는 스킬은 확장하지 않는다."""
        if not input_text.startswith("/"):
            return input_text
        parts = input_text[1:].split(None, 1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        skill = self.get(command, agent)
        if not skill:
            return input_text
        return skill.content.replace("{{args}}", args).replace("{{input}}", args)

    async def load_directory(self, path: str) -> list[str]:
        loaded: list[str] = []
        dir_path = Path(path).expanduser()
        if not dir_path.exists():
            return loaded

        for md_file in list(dir_path.glob("*.md")) + list(dir_path.glob("*.yaml")):
            try:
                skill = _parse_skill_file(md_file)
                if skill:
                    self.register(skill)
                    loaded.append(skill.name)
            except Exception as exc:
                logger.info(f"[SkillRegistry] Failed to load {md_file.name}: {exc}")

        return loaded


def _skill_fields(meta: dict[str, Any], default_name: str) -> tuple[str, str, list[str]]:
    """YAML 이 정한 아무 타입을 이름, 설명, 별칭으로 검사한다. 틀리면 ValueError(그 파일만 건너뛴다)."""
    name = meta.get("name", default_name)
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"name must be a non-empty string, got {name!r}")
    description = meta.get("description", "")
    if description is None:
        description = ""
    if not isinstance(description, str):
        raise ValueError(f"description must be a string, got {description!r}")
    aliases = meta.get("aliases", [])
    if aliases is None:
        aliases = []
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise ValueError(f"aliases must be a list of strings, got {aliases!r}")
    return name, description, aliases


def _parse_skill_file(path: Path) -> Skill | None:
    if path.suffix == ".md":
        post = frontmatter.load(str(path))
        # frontmatter 값은 YAML 이 정한 아무 타입이라 Any. 쓰는 세 필드는 _skill_fields 가 검사한다
        meta: dict[str, Any] = dict(post.metadata)
        name, description, aliases = _skill_fields(meta, path.stem)
        return Skill(name=name, description=description, aliases=aliases, content=post.content, metadata=meta)
    elif path.suffix == ".yaml":
        with open(path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError("skill yaml must be a mapping")
        name, description, aliases = _skill_fields(data, path.stem)
        content = data.get("content", "")
        if not isinstance(content, str):
            raise ValueError(f"content must be a string, got {type(content).__name__}")
        return Skill(name=name, description=description, aliases=aliases, content=content, metadata=data)
    return None
