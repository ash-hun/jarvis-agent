"""[core] loan_rules.yaml 의 대출 상품, 규제를 읽고 프로필과 집값으로 자격, 금리, 대출 한도를 정하는 순수 함수."""

import yaml
from typing import Any
from pathlib import Path
from datetime import date
from functools import cache
from dataclasses import dataclass, field

from jarvis.core.tools.housing.profile import HousingProfile
from jarvis.core.tools.housing.loan import annuity_payment

RULES_PATH = Path(__file__).with_name("loan_rules.yaml")
OK, NO, UNKNOWN = "가능", "불가", "미확인"


@dataclass(frozen=True)
class Area:
    """공고 지역. regulated 가 None 이면 규제지역인지 모른다(경기도 일부만 규제지역이다)."""

    capital: bool
    regulated: bool | None

    @property
    def strict(self) -> bool | None:
        """수도권이거나 규제지역. 규제를 몰라도 수도권이면 참이다."""
        return True if self.capital or self.regulated else None if self.regulated is None else False


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    purpose: str  # purchase | deposit
    raw: dict[str, Any] = field(hash=False, compare=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)


@dataclass(frozen=True)
class Rules:
    checked: date
    stale_after_days: int
    regulation: dict[str, Any]
    products: tuple[Product, ...]
    notice_kinds: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    def stale(self, today: date) -> bool:
        return (today - self.checked).days > self.stale_after_days

    def area(self, region: str, title: str) -> Area:
        text = f"{region} {title}"
        capital = any(region.startswith(name) for name in self.regulation["capital_areas"])
        if any(name in text for name in self.regulation["regulated_areas"]):
            return Area(capital, True)
        partly = any(region.startswith(name) for name in self.regulation["partly_regulated"])
        return Area(capital, None if partly else False)


@dataclass(frozen=True)
class Verdict:
    status: str  # 가능 | 불가 | 미확인
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Limit:
    """대출 한도와 그 내역(어느 조건이 얼마를 막았는지)."""

    amount: float
    parts: tuple[tuple[str, float], ...]
    notes: tuple[str, ...] = ()


@cache
def load_rules(path: Path = RULES_PATH) -> Rules:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    products = tuple(Product(p["id"], p["name"], p["purpose"], p) for p in data["products"])
    return Rules(data["checked"], int(data["stale_after_days"]), data["regulation"], products,
                 data.get("notice_kinds") or {})


def _by_area(value: Any, area: Area) -> Any:
    """{capital: x, other: y} 꼴이면 지역으로 고르고, 아니면 그대로."""
    if isinstance(value, dict) and "capital" in value:
        return value["capital"] if area.capital else value["other"]
    return value


def _single(product: Product, profile: HousingProfile, today: date) -> bool:
    """미혼 단독세대주 조건(디딤돌의 줄어든 한도)을 받는가."""
    age = profile.age_on(today)
    return bool(product.get("single")) and profile.married is False and age is not None


def eligibility(product: Product, profile: HousingProfile, today: date, price: float | None = None,
                area: Area | None = None) -> Verdict:
    """프로필(그리고 주면 집값)로 본 자격. 모르는 값이 걸리면 미확인과 그 조건을 돌려준다."""
    no: list[str] = []
    unknown: list[str] = []
    if product.get("homeless"):
        if profile.homeless is False:
            no.append("무주택자만")
        elif profile.homeless is None:
            unknown.append("무주택자만")
    income_max = product.get("income_max")
    if profile.married and product.get("income_max_married"):
        income_max = product.get("income_max_married")
    elif profile.first_home and product.get("income_max_first_home"):
        income_max = product.get("income_max_first_home")
    if income_max:
        rule = f"연소득 {income_max / 10_000:,.0f}만원 이하"
        if profile.income is None:
            unknown.append(rule)
        elif profile.income > income_max:
            no.append(rule)
    assets_max = product.get("assets_max")
    if assets_max:
        rule = f"순자산 {assets_max / 100_000_000:g}억원 이하"
        if profile.assets is None:
            unknown.append(rule)
        elif profile.assets > assets_max:
            no.append(rule)
    age = profile.age_on(today)
    age_range = product.get("age_range")
    if age_range:
        rule = f"만 {age_range[0]}~{age_range[1]}세"
        if age is None:
            unknown.append(rule)
        elif not age_range[0] <= age <= age_range[1]:
            no.append(rule)
    min_age = product.get("single_min_age")
    if min_age:
        rule = f"만 {min_age}세 미만 미혼 단독세대주 제외(부양가족이 있으면 예외)"
        if profile.married is None or (profile.married is False and age is None):
            unknown.append(rule)
        elif profile.married is False and age is not None and age < min_age:
            no.append(rule)
    if price is not None and area is not None:
        limit = _price_max(product, profile, today, area)
        if limit and price > limit:
            what = "집값" if product.purpose == "purchase" else "보증금"
            no.append(f"{what} {limit / 100_000_000:g}억원 이하")
    if no:
        return Verdict(NO, tuple(no))
    return Verdict(UNKNOWN if unknown else OK, tuple(unknown))


def unit_mismatch(rules: Rules, unit: str, profile: HousingProfile, today: date) -> str | None:
    """주택형 이름의 공급대상과 프로필이 어긋나면 그 대상(예: 신혼부부). 맞거나 모르면 None."""
    age = profile.age_on(today)
    for target in rules.notice_kinds.get("unit_targets", ()):
        if target["word"] not in unit or any(word in unit for word in target.get("unless", ())):
            continue
        need, value = target["need"], target.get("value")
        if need == "age_min":
            off = age is not None and age < value
        elif need == "age_range":
            off = age is not None and not value[0] <= age <= value[1]
        else:
            off = getattr(profile, need) is False
        if off:
            return str(target["who"])
    return None


def notice_access(rules: Rules, kind: str, title: str, profile: HousingProfile) -> Verdict:
    """공고 유형으로 본 신청 가능성. 가구원 수와 공고별 기준을 몰라 불가도 '가능성 낮음'으로만 쓴다."""
    kinds = rules.notice_kinds
    married_only = kinds.get("married_only")
    if married_only and married_only["match"] in kind:
        who = f"공급대상: {married_only['who']}"
        basis = f"근거: {married_only['source']}"
        if profile.married is False:
            return Verdict(NO, (married_only["single_path"], who, basis))
        return Verdict(OK if profile.married else UNKNOWN, (who, basis))
    if any(word in title for word in kinds.get("relaxed_words", ())):
        return Verdict(OK, ("제목에 자격완화: 소득, 자산 기준을 완화하거나 뺀 모집(무주택 등 나머지는 공고문 확인)",))
    rule = next((r for r in kinds.get("income", ()) if r["match"] in kind), None)
    if rule is None:
        return Verdict(UNKNOWN, ("공고문 신청자격 확인",))
    basis = f"{rule['basis']}. 근거: {rule['source']}"
    if profile.welfare and rule.get("welfare"):
        return Verdict(OK, (rule["welfare"], basis))
    if profile.student and rule.get("student"):
        return Verdict(UNKNOWN, (rule["student"], basis))
    limit = int(rule["monthly_one_person"])
    text = f"소득 기준 1인 가구 월 {limit:,}원 이하"
    if profile.income is None:
        return Verdict(UNKNOWN, (text, "소득을 몰라 대 보지 못했다", basis))
    monthly = round(profile.income / 12)
    if monthly <= limit:
        return Verdict(OK, (f"{text} 안(프로필 월 {monthly:,}원)", basis))
    over = f"{text}인데 프로필 소득은 월 {monthly:,}원"
    # ponytail: 가구원수별 기준표 없이 1인 기준만 댄다(공개 표끼리 2인 값이 어긋나 옮기지 않았다),
    # 공고문 원문의 가구원수별 표를 확인하면 notice_kinds 에 넣어 2인 이상도 가른다
    if profile.household is not None and profile.household > 1:
        return Verdict(UNKNOWN, (over, f"{profile.household}인 가구 기준은 더 높아 공고문으로 확인한다", basis))
    if profile.household is None:
        return Verdict(NO, (over, "가구원이 많으면 기준이 올라간다(프로필에 가구원수가 없다)", basis))
    return Verdict(NO, (over, basis))


def _price_max(product: Product, profile: HousingProfile, today: date, area: Area) -> float | None:
    if product.purpose == "deposit":
        value = _by_area(product.get("deposit_max"), area)
    elif _single(product, profile, today):
        value = product.get("single")["price_max"]
    elif profile.married and product.get("price_max_married"):
        value = product.get("price_max_married")
    else:
        value = product.get("price_max")
    return float(value) if value else None


def rate_range(product: Product, years: int, area: Area) -> tuple[float, float]:
    """연 금리 범위(하단, 상단). 만기별 금리표가 있으면 그 만기의 값에 규제지역 가산을 더한다."""
    table = product.get("rate_by_years")
    if table:
        base = float(table.get(years) or table[min(table, key=lambda y: abs(y - years))])
        add = float(product.get("regulated_add") or 0)
        low = base + (add if area.regulated else 0)
        high = base + (add if area.regulated is not False else 0)
        return low, high
    low, high = product.get("rate")
    return float(low), float(high)


def product_years(product: Product, rules: Rules, area: Area, profile: HousingProfile, today: date,
                  wanted: int | None) -> tuple[int, str | None]:
    """대출 기간과, 원하는 기간을 줄였다면 그 이유."""
    years = wanted or int(product.get("years") or 30)
    mortgage = rules.regulation["mortgage"]
    if product.get("market") and area.strict is not False and years > mortgage["max_years_capital_or_regulated"]:
        cap = mortgage["max_years_capital_or_regulated"]
        return cap, f"수도권, 규제지역 주담대는 {cap}년 이내"
    age = profile.age_on(today)
    reason = None
    for long_years, age_max in sorted((product.get("years_age_max") or {}).items(), reverse=True):
        if years >= int(long_years) and (age is None or age >= age_max):
            years, reason = int(long_years) - 10, f"{long_years}년 만기는 만 {age_max}세 미만"
    return years, reason


def loan_limit(product: Product, rules: Rules, profile: HousingProfile, today: date, price: float, area: Area,
               years: int, high_rate: float) -> Limit:
    """대출 한도 = 상품 한도, LTV(보증금 비율), 규제 한도, DSR/DTI 한도 중 가장 작은 값."""
    parts: list[tuple[str, float]] = []
    notes: list[str] = []
    mortgage = rules.regulation["mortgage"]
    if product.purpose == "deposit":
        cap = _by_area(product.get("cap"), area)
        if cap:
            parts.append(("상품 한도", float(cap)))
        married = profile.married and product.get("ratio_married")
        ratio = product.get("ratio_married") if married else product.get("ratio")
        parts.append((f"보증금의 {ratio}%", price * ratio / 100))
        return Limit(min(v for _, v in parts), tuple(parts))
    if product.get("market"):
        ltv = _market_ltv(mortgage, profile, area)
        parts.append((f"LTV {ltv}%", price * ltv / 100))
        if area.strict:
            cap = next(c["cap"] for c in mortgage["caps_capital_or_regulated"]
                       if c["price_max"] is None or price <= c["price_max"])
            parts.append(("수도권, 규제지역 주담대 한도", float(cap)))
    else:
        parts.append(("상품 한도", float(_product_cap(product, profile, today))))
        ltv = _policy_ltv(product, profile, area)
        parts.append((f"LTV {ltv}%", price * ltv / 100))
    ratio = product.get("debt_ratio")
    if ratio:
        if profile.income is None:
            notes.append(f"소득을 몰라 {ratio['kind']} 한도를 빼고 셌다")
        else:
            test_rate = high_rate
            label = f"{ratio['kind']} {ratio['limit']}%"
            if ratio["kind"] == "DSR":
                stress = mortgage["stress_rate"]["capital_or_regulated" if area.strict else "other"]
                test_rate += stress
                label += f"(스트레스 +{stress:g}%p)"
            monthly = profile.income * ratio["limit"] / 100 / 12
            parts.append((label, max_principal(monthly, test_rate, years)))
    return Limit(max(0.0, min(v for _, v in parts)), tuple(parts), tuple(notes))


def _market_ltv(mortgage: dict[str, Any], profile: HousingProfile, area: Area) -> int:
    if profile.first_home:
        return int(mortgage["ltv_first_home"]["capital_or_regulated" if area.strict else "other"])
    return int(mortgage["ltv"]["regulated" if area.regulated else "other"])


def _policy_ltv(product: Product, profile: HousingProfile, area: Area) -> int:
    ltv = int(product.get("ltv"))
    if profile.first_home and product.get("ltv_first_home"):
        strict = product.get("ltv_first_home_capital_or_regulated")
        return int(strict) if strict and area.strict else int(product.get("ltv_first_home"))
    if area.regulated and product.get("regulated_ltv_cut") and not profile.first_home:
        ltv -= int(product.get("regulated_ltv_cut"))
    return ltv


def _product_cap(product: Product, profile: HousingProfile, today: date) -> float:
    source = product.get("single") if _single(product, profile, today) else product.raw
    if profile.married and source.get("cap_married"):
        return float(source["cap_married"])
    if profile.first_home and source.get("cap_first_home"):
        return float(source["cap_first_home"])
    return float(source["cap"])


def max_principal(monthly: float, annual_rate: float, years: int) -> float:
    """원리금균등으로 매달 monthly 를 낼 때 빌릴 수 있는 원금."""
    unit = annuity_payment(1.0, annual_rate / 100 / 12, years * 12)
    return monthly / unit if unit else 0.0
