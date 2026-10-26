"""[core] 대출과 공공주택 신청 자격을 가르는 사용자의 주거 조건과 그 변경 규칙."""

import re
import hashlib
from datetime import date
from typing import TYPE_CHECKING, Any
from dataclasses import asdict, dataclass, fields, replace

from jarvis.core.tools.housing.lh_notice import resolve_region
from jarvis.core.tools.housing.amount import parse_won
from jarvis.memory.scope import LOCAL_USER

if TYPE_CHECKING:
    from jarvis.memory.memory_service import MemoryService
    from jarvis.memory.scope import MemoryScope

PROFILE_SOURCE = "housing_profile"
# 사용자가 쓰는 말과 필드 이름. /housing set 과 housing_profile 도구가 같이 쓴다
ALIASES = {
    "homeless": "homeless", "무주택": "homeless",
    "first_home": "first_home", "생애최초": "first_home",
    "married": "married", "혼인": "married", "결혼": "married", "기혼": "married",
    "income": "income", "소득": "income", "연소득": "income",
    "assets": "assets", "순자산": "assets", "자산": "assets",
    "birth_date": "birth_date", "생년월일": "birth_date",
    "age": "age", "나이": "age", "만나이": "age",
    "household": "household", "가구원": "household", "가구원수": "household", "세대원수": "household",
    "welfare": "welfare", "수급자": "welfare", "기초수급": "welfare", "기초생활수급": "welfare",
    "student": "student", "대학생": "student",
    "regions": "regions", "관심지역": "regions", "지역": "regions", "희망지역": "regions",
}
_YES = {"true", "yes", "y", "1", "예", "네", "응", "어", "o", "맞음", "있음", "가능", "미사용", "무주택", "기혼",
        "결혼", "수급", "재학", "휴학"}
_NO = {"false", "no", "n", "0", "아니오", "아니", "x", "없음", "불가", "사용", "유주택", "미혼", "비수급", "졸업"}
_UNSET = {"", "none", "null", "모름", "삭제", "비움"}
KNOWN = "무주택, 생애최초, 혼인, 연소득, 순자산, 생년월일, 나이, 가구원수, 수급자, 대학생, 관심지역"
FLAGS = ("homeless", "first_home", "married", "welfare", "student")
NATIONWIDE = "전국"


@dataclass(frozen=True)
class HousingProfile:
    """비운 값(None)은 모르는 것이다. 모르는 조건이 걸린 상품은 자격을 두 경우로 펼친다."""

    homeless: bool | None = None  # 세대원 전원 무주택
    first_home: bool | None = None  # 생애최초 혜택을 아직 쓰지 않았다
    married: bool | None = None
    income: int | None = None  # 연소득(원). 미혼은 본인, 기혼은 부부 합산
    assets: int | None = None  # 순자산(원)
    birth_date: date | None = None
    age: int | None = None  # 생년월일이 없을 때의 만 나이
    age_as_of: date | None = None  # age 를 받은 날. 해가 지나면 그만큼 더한다
    household: int | None = None  # 본인을 넣은 세대 구성원 수. 공공임대 소득 기준이 이것으로 달라진다
    welfare: bool | None = None  # 기초생활 수급자(생계, 의료, 주거급여 중 하나)
    student: bool | None = None  # 대학생(재학, 휴학 포함). 행복주택 대학생 계층
    # 관심 지역. 공고 도구가 지역을 따로 받지 않으면 전국 대신 이 지역들로 찾는다
    regions: tuple[str, ...] | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))

    def age_on(self, today: date) -> int | None:
        """만 나이. 생년월일이 있으면 정확히, 만 나이만 있으면 받은 날부터 지난 해만큼 더한다(1살 오차 가능)."""
        if self.birth_date is not None:
            b = self.birth_date
            return today.year - b.year - ((today.month, today.day) < (b.month, b.day))
        if self.age is None:
            return None
        if self.age_as_of is None:
            return self.age
        return self.age + max(0, (today - self.age_as_of).days // 365)

    def metadata(self) -> dict[str, Any]:
        return {k: v.isoformat() if isinstance(v, date) else v for k, v in asdict(self).items() if v is not None}

    def lines(self, today: date) -> list[str]:
        def yn(value: bool | None, yes: str, no: str) -> str:
            return "모름" if value is None else yes if value else no

        age = self.age_on(today)
        age_text = "모름" if age is None else f"만 {age}세" + ("" if self.birth_date else " (생년월일 없음, 추정)")
        return [
            f"무주택: {yn(self.homeless, '예', '아니오')}",
            f"생애최초: {yn(self.first_home, '가능(미사용)', '불가(사용함)')}",
            f"혼인: {yn(self.married, '기혼', '미혼')}",
            f"연소득: {'모름' if self.income is None else f'{self.income:,}원'}",
            f"순자산: {'모름' if self.assets is None else f'{self.assets:,}원'}",
            f"나이: {age_text}",
            f"가구원수: {'모름' if self.household is None else f'{self.household}명'}",
            f"수급자: {yn(self.welfare, '예', '아니오')}",
            f"대학생: {yn(self.student, '예', '아니오')}",
            f"관심 지역: {', '.join(self.regions) if self.regions else '없음(전국)'}",
        ]


def regions_or_home(raw: Any, profile: HousingProfile) -> list[str]:
    """도구가 받은 지역(쉼표로 여럿). 비었으면 프로필의 관심 지역, 그것도 없으면 전국. 순수 함수."""
    given = [r.strip() for r in str(raw or "").replace("/", ",").split(",") if r.strip()]
    return given or list(profile.regions or ()) or [NATIONWIDE]


def from_metadata(meta: dict[str, Any]) -> HousingProfile:
    values: dict[str, Any] = {}
    for f in fields(HousingProfile):
        raw = meta.get(f.name)
        if raw is None:
            continue
        if f.name in ("birth_date", "age_as_of"):
            values[f.name] = date.fromisoformat(raw)
        elif f.name == "regions":
            values[f.name] = tuple(raw)
        else:
            values[f.name] = raw
    return HousingProfile(**values)


def _flag(raw: str) -> bool:
    word = raw.strip().lower()
    if word in _YES:
        return True
    if word in _NO:
        return False
    raise ValueError(f"예/아니오로 읽을 수 없다: {raw}")


def _count(raw: str) -> int:
    match = re.fullmatch(r"(\d{1,2})\s*(?:명|인|인가구|인 가구)?", raw.strip())
    if match is None or int(match.group(1)) < 1:
        raise ValueError(f"가구원수를 읽을 수 없다: {raw}")
    return int(match.group(1))


def _regions(raw: Any) -> tuple[str, ...]:
    """'서울, 경기' 나 ['서울', '경기'] 를 게시판이 아는 지역 이름 묶음으로. 같은 지역을 두 번 써도 하나다."""
    words = raw if isinstance(raw, (list, tuple)) else re.split(r"[,/\s]+", str(raw))
    names = tuple(dict.fromkeys(w.strip() for w in words if str(w).strip()))
    unknown = [n for n in names if resolve_region(n) is None]
    if unknown:
        raise ValueError(f"모르는 지역: {', '.join(unknown)}")
    if not names or any(resolve_region(n) == "" for n in names):
        raise ValueError("관심 지역은 시도 이름이다(전국은 지우기로). 예: 서울, 경기")
    return names


def _age(raw: str) -> int:
    match = re.fullmatch(r"(?:만\s*)?(\d{1,3})\s*(?:세|살)?", raw.strip())
    if match is None:
        raise ValueError(f"나이를 읽을 수 없다: {raw}")
    return int(match.group(1))


def _birth(raw: str) -> date:
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 8:
        raise ValueError(f"생년월일은 YYYY-MM-DD 다: {raw}")
    return date(int(digits[:4]), int(digits[4:6]), int(digits[6:]))


def apply_updates(profile: HousingProfile, updates: dict[str, Any], today: date) -> HousingProfile:
    """{이름: 값} 을 반영한 새 프로필. 모르는 이름, 읽을 수 없는 값은 ValueError. 같은 값을 다시 넣어도 같다."""
    changes: dict[str, Any] = {}
    for key, raw in updates.items():
        name = ALIASES.get(str(key).strip().lower().replace(" ", ""))
        if name is None:
            raise ValueError(f"모르는 항목: {key} (쓸 수 있는 것: {KNOWN})")
        text = str(raw).strip()
        if text.lower() in _UNSET:
            changes[name] = None
            if name == "age":
                changes["age_as_of"] = None
            continue
        if name in FLAGS:
            changes[name] = raw if isinstance(raw, bool) else _flag(text)
        elif name == "household":
            changes[name] = raw if isinstance(raw, int) else _count(text)
        elif name in ("income", "assets"):
            changes[name] = parse_won(raw)
        elif name == "birth_date":
            changes[name] = _birth(text)
        elif name == "regions":
            changes[name] = _regions(raw)
        else:
            changes["age"] = int(raw) if isinstance(raw, int) else _age(text)
            changes["age_as_of"] = today
    return replace(profile, **changes)


def parse_pairs(text: str) -> dict[str, str]:
    """'연소득=6000만 혼인=미혼' 또는 '연소득 6000만, 혼인 미혼' 을 {이름: 값} 으로."""
    pairs: dict[str, str] = {}
    for part in re.split(r"[,\n]|\s+(?=\S+\s*=)", text):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep:
            key, _, value = part.partition(" ")
        pairs[key.strip()] = value.strip()
    return pairs


def profile_id(user_id: str) -> str:
    """자연 키: 사용자. 에이전트가 달라도 한 사용자의 주거 조건은 하나다."""
    return "hp_" + hashlib.sha1(f"{user_id}|{PROFILE_SOURCE}".encode()).hexdigest()[:29]


class ProfileStore:
    """주거 프로필을 사용자 장기 기억의 한 항목으로 읽고 쓴다. 같은 사용자는 늘 같은 항목을 덮는다."""

    def __init__(self, memory: "MemoryService") -> None:
        self._memory = memory

    async def get(self, user_id: str) -> HousingProfile:
        item = await self._memory.get(profile_id(user_id))
        return from_metadata(item.metadata) if item is not None else HousingProfile()

    async def save(self, profile: HousingProfile, scope: "MemoryScope", today: date) -> None:
        from jarvis.memory.types import MemoryKind

        user = scope.user_id or LOCAL_USER
        content = "주거 프로필(대출 자격 판단용): " + ", ".join(profile.lines(today))
        # 모든 에이전트가 보는 사용자 사실이다. 같은 id 로 덮어 다시 저장해도 하나만 남는다
        await self._memory.remember(
            content, source=PROFILE_SOURCE, scope=scope.with_session(None), kind=MemoryKind.SEMANTIC,
            visibility="shared", author="user", metadata=profile.metadata(), importance=0.8, item_id=profile_id(user),
        )

    async def clear(self, user_id: str) -> bool:
        if await self._memory.get(profile_id(user_id)) is None:
            return False
        await self._memory.forget(profile_id(user_id))
        return True
