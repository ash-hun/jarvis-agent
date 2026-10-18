"""[scripts] Focus 조사 결과(references.md)가 지시문의 형식을 지켰는지 채점한다."""

import re
import sys
import json
from pathlib import Path

MARKER = "## 조사: "
MAX_PRECEDENTS = 3
MAX_FEATURES = 2
MAX_FEATURE_CHARS = 60
HANGUL = re.compile(r"[가-힣]")
LATIN_WORD = re.compile(r"[A-Za-z]{4,}")
URL = re.compile(r"https?://|(?:^|\s)[\w.-]+\.[a-z]{2,}/")


def check_section(section: str) -> dict[str, object]:
    """조사 한 건. 선례 블록은 '### ' 부터 다음 '###' 전까지, '#### 적용할 점' 은 따로 본다."""
    body, _, _apply = section.partition("#### 적용할 점")
    blocks = [b for b in re.split(r"\n(?=### )", body) if b.startswith("### ")]
    url_ok = feature_count_ok = feature_len_ok = korean_ok = 0
    features_total = 0
    for block in blocks:
        lines = [line.strip() for line in block.splitlines()[1:] if line.strip()]
        sources = [line for line in lines if line.startswith("- 출처")]
        # 특징은 출처가 아닌 모든 항목 줄이다. 번호 목록과 들여 쓴 하위 항목도 특징으로 센다(형식 위반이 숨지 않게)
        features = [
            re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line)
            for line in lines
            if re.match(r"^(?:[-*]|\d+[.)])\s+", line) and not line.startswith("- 출처")
        ]
        features_total += len(features)
        url_ok += any(URL.search(s) for s in sources)
        feature_count_ok += 0 < len(features) <= MAX_FEATURES
        # 특징이 하나도 없으면 길이 규칙을 지킨 것으로 치지 않는다
        feature_len_ok += bool(features) and all(len(f) <= MAX_FEATURE_CHARS for f in features)
        # 한국어로 썼는가: 한글이 있고 4글자 이상 영어 단어가 고유명사 수준(3개 이하)인가
        korean_ok += bool(features) and all(HANGUL.search(f) and len(LATIN_WORD.findall(f)) <= 3 for f in features)
    return {
        "precedents": len(blocks),
        "precedents_ok": 0 < len(blocks) <= MAX_PRECEDENTS,
        "numbered_list": bool(re.search(r"^\s*\d+[.)]\s", body, re.MULTILINE)),
        "source_url": f"{url_ok}/{len(blocks)}",
        "features_le_2": f"{feature_count_ok}/{len(blocks)}",
        "features_le_60_chars": f"{feature_len_ok}/{len(blocks)}",
        "korean": f"{korean_ok}/{len(blocks)}",
        "chars": len(section),
    }


def main() -> None:
    for path in sys.argv[1:]:
        text = Path(path).read_text(encoding="utf-8")
        sections = [MARKER + s for s in text.split(MARKER)[1:]]
        print(json.dumps({"file": path, "sections": [check_section(s) for s in sections]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
