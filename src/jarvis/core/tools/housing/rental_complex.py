"""[core] LH 임대주택검색의 단지별 임대보증금과 월임대료를 읽고, 공고 제목을 그 단지에 맞추는 함수."""

import re
import json
from dataclasses import dataclass

from jarvis.core.tools.housing.fetch import Fetch, FetchError

COMPLEX_URL = "https://apply.lh.or.kr/lhapply/csvc/lshs_sch/ajax.do"
# 한 번에 지역 전체를 받는다. 경기도가 약 2,100행이라 넉넉히 둔다
COMPLEX_PAGE_SIZE = "5000"
# 단지 이름에서 블록 표기(A1블록, A-1BL, B2 블록)를 같은 꼴로 맞춘다
_BLOCK_RE = re.compile(r"\b([A-Z])\s*-?\s*(\d+)(?:\s*\(\d+\))?\s*(?:블록|BL|bl)?")
_PLACE_RE = re.compile(r"^(?:\[[^\]]*\]\s*)*(?:\([^)]*\)\s*)*([가-힣]+\d*)")


@dataclass(frozen=True)
class ComplexUnit:
    """임대주택검색의 한 행. 같은 단지가 전용면적마다 여러 행이다."""

    name: str
    kind: str  # 국민임대, 행복주택 등
    area: float
    deposit: int
    rent: int


def complex_query(region_code: str) -> dict[str, str]:
    """검색 화면이 보내는 값과 같다. 빠진 칸이 있으면 빈 목록이 온다."""
    return {
        "cbo_SearchSiDo": region_code, "cbo_SearchSi": "", "cbo_SearchSplTp": "", "cbo_SearchLsGmy": "0",
        "cbo_SearchRfe": "0", "listCo": COMPLEX_PAGE_SIZE, "currPage": "1", "CS_CD": "", "CNP_CD": region_code,
        "SGG_CD": "", "SPL_TP_CD": "",
    }


def parse_complexes(body: str) -> list[ComplexUnit]:
    try:
        rows = json.loads(body).get("list") or []
    except (json.JSONDecodeError, AttributeError) as exc:
        raise FetchError(f"임대주택검색이 JSON 이 아닌 응답을 줬다: {body[:80]}") from exc
    units = []
    for row in rows:
        try:
            units.append(ComplexUnit(
                str(row["sbdLgoNm"]), str(row.get("aisTpCdNm", "")), float(row.get("ddoAr") or 0),
                int(row.get("lsGmy") or 0), int(row.get("rfe") or 0),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return units


async def fetch_complexes(fetch: Fetch, region_code: str) -> list[ComplexUnit]:
    return parse_complexes(await fetch(COMPLEX_URL, complex_query(region_code)))


def place_and_block(title: str) -> tuple[str, str]:
    """공고 제목이나 단지 이름의 앞 지명(예: 의왕청계2)과 블록(예: A1). 없으면 빈 문자열."""
    place = _PLACE_RE.match(title.strip())
    block = _BLOCK_RE.search(title.upper())
    return (place.group(1) if place else ""), (f"{block.group(1)}{block.group(2)}" if block else "")


def kind_of(notice_kind: str) -> str:
    """공고 유형을 단지 공급유형으로. '행복주택(신혼희망)' 은 단지에서 '행복주택' 이다."""
    return notice_kind.split("(")[0].strip()


def match_complex(title: str, notice_kind: str, units: list[ComplexUnit]) -> list[ComplexUnit]:
    """공고와 같은 단지의 행들. 지명, 블록, 공급유형이 맞는 단지가 하나일 때만 돌려준다.

    블록이 없는 공고(예: '하남시 신혼희망타운')는 같은 지명 단지가 여럿이라 고르지 않는다. 틀린 금액보다 모름이 낫다.
    """
    place, block = place_and_block(title)
    if not place or not block:
        return []
    kind = kind_of(notice_kind)
    # 공급유형이 정확히 같은 행만 쓴다. '국민·영구임대' 단지의 국민임대 금액을 영구임대 공고에 붙이면 틀린다
    same = [u for u in units if place_and_block(u.name) == (place, block) and (not kind or u.kind == kind)]
    if len({u.name for u in same}) != 1:
        return []
    # 금액이 0 인 행은 아직 금액이 정해지지 않은 신규 단지다
    return [u for u in same if u.deposit > 0]
