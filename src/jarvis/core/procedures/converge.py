"""[core] 세대마다 따로 쌓인 옛 EDM 절차 파일을 (에이전트, 작업 종류)당 하나로 모으는 계획을 세우는 순수 함수."""

import re
from dataclasses import dataclass, replace

from jarvis.core.procedures.procedures_store import STATUS_DRAFT, Procedure

# 세대를 출처에 넣던 때의 키 "edm:<에이전트>:<작업 종류>:<세대>"
LEGACY_SOURCE_RE = re.compile(r"^(edm:[^:]+:.+):(\d+)$")


@dataclass(frozen=True)
class Convergence:
    keep: Procedure  # 새 출처와 세대로 고쳐 저장할 절차(개정 초안 포함)
    archive: tuple[str, ...]  # 보관 폴더로 옮길 파일 이름. 지우지 않는다


def plan_convergence(procedures: list[Procedure]) -> list[Convergence]:
    """옛 출처가 하나라도 낀 묶음만 고친다. 다 고친 저장소에는 빈 목록이라 두 번 돌려도 같다.

    남길 것: 승인된 것 중 가장 늦은 세대, 승인된 것이 없으면 가장 늦은 세대.
    남긴 것이 승인됐고 더 늦은 세대의 초안이 있으면 그 초안을 개정으로 붙인다. 나머지는 보관한다.
    """
    groups: dict[str, list[tuple[int, Procedure]]] = {}
    legacy: set[str] = set()
    for p in procedures:
        match = LEGACY_SOURCE_RE.match(p.source)
        key, gen = (match.group(1), int(match.group(2))) if match else (p.source, p.generation)
        if match:
            legacy.add(key)
        groups.setdefault(key, []).append((gen, p))
    plans: list[Convergence] = []
    for key in sorted(legacy):
        members = sorted(groups[key], key=lambda gp: (gp[1].approved, gp[0], gp[1].name))
        gen, keeper = members[-1]
        keep = replace(keeper, source=key, generation=max(gen, keeper.generation))
        newer = [(g, p) for g, p in members if not p.approved and g > gen]
        if keeper.approved and newer and keep.revision is None:
            rev_gen, rev = max(newer, key=lambda gp: gp[0])
            keep = replace(keep, revision=replace(rev, source=key, generation=rev_gen, status=STATUS_DRAFT))
        archive = tuple(p.name for _, p in members if p.name != keeper.name)
        plans.append(Convergence(keep=keep, archive=archive))
    return plans
