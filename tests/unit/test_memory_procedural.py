"""memory 기능의 절차 기억 출처: 이름과 별칭의 온전한 일치, 스킬 레지스트리를 매번 새로 읽기."""

import pytest
from types import SimpleNamespace

from jarvis.memory.long_term.procedural import (
    InMemoryProcedures,
    ProceduralSource,
    Procedure,
    SkillRegistryProcedures,
)


@pytest.mark.parametrize(
    "source", [InMemoryProcedures(), SkillRegistryProcedures(object())], ids=["in_memory", "skill_registry"]
)
def test_concrete_procedure_sources_inherit_the_base(source):
    assert isinstance(source, ProceduralSource)


def test_procedural_source_base_knows_nothing():
    assert ProceduralSource().match("deploy") == []


def test_in_memory_procedures_match_by_name_or_alias():
    source = InMemoryProcedures([Procedure(name="deploy", description="배포", aliases=("배포",))])
    source.add(Procedure(name="review", description="리뷰"))

    assert [p.name for p in source.match("스테이징 배포 해줘")] == ["deploy"]
    assert [p.name for p in source.match("review this")] == ["review"]
    assert source.match("deployment") == []


def test_skill_registry_procedures_read_registry_live():
    skills = [SimpleNamespace(name="deploy", description=None, aliases=["배포"])]
    source = SkillRegistryProcedures(SimpleNamespace(list_all=lambda: skills))

    matched = source.match("배포")
    skills.append(SimpleNamespace(name="lint", description="정적 검사"))

    assert [(p.name, p.description, p.aliases) for p in matched] == [("deploy", "", ("배포",))]
    assert [p.name for p in source.match("lint")] == ["lint"]
    assert SkillRegistryProcedures(object()).match("deploy") == []
