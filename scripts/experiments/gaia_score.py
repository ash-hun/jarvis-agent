"""[scripts] GAIA 공식 scorer 의 정규화와 정답 일치 판정, FINAL ANSWER 줄 파싱을 순수 함수로 둔다."""

# 채점 함수는 GAIA 리더보드 Space 의 scorer.py 를 그대로 옮겼다(print 와 warnings 만 뺐다).
# 출처: https://huggingface.co/spaces/gaia-benchmark/leaderboard/blob/main/scorer.py (Apache-2.0)

import re
import string

FINAL_ANSWER = re.compile(r"FINAL ANSWER\s*[:：]\s*(.+)", re.I)
SUMMARY_ANSWER = re.compile(r"지금까지의 답\s*\**\s*[:：]\s*(.+)")


def normalize_number_str(number_str: str) -> float:
    """$, %, 쉼표를 지우고 float 로. 바뀌지 않으면 inf 라 어떤 정답과도 같지 않다."""
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    try:
        return float(number_str)
    except ValueError:
        return float("inf")


def split_string(s: str, char_list: tuple[str, ...] = (",", ";")) -> list[str]:
    pattern = f"[{''.join(char_list)}]"
    return re.split(pattern, s)


def normalize_str(input_str: str, remove_punct: bool = True) -> str:
    """공백을 모두 지우고(seagull 과 sea gull) 소문자로. remove_punct 면 구두점도 지운다."""
    no_spaces = re.sub(r"\s", "", input_str)
    if remove_punct:
        return no_spaces.lower().translate(str.maketrans("", "", string.punctuation))
    return no_spaces.lower()


def _is_float(element: str) -> bool:
    try:
        float(element)
        return True
    except ValueError:
        return False


def question_scorer(model_answer: str | None, ground_truth: str) -> bool:
    """정답이 숫자면 숫자로, 쉼표나 세미콜론이 있으면 원소별로, 아니면 정규화한 문자열로 비교한다."""
    if model_answer is None:
        model_answer = "None"
    if _is_float(ground_truth):
        return normalize_number_str(model_answer) == float(ground_truth)
    if any(char in ground_truth for char in [",", ";"]):
        gt_elems, ma_elems = split_string(ground_truth), split_string(model_answer)
        if len(gt_elems) != len(ma_elems):
            return False
        comparisons = []
        for ma_elem, gt_elem in zip(ma_elems, gt_elems, strict=True):
            if _is_float(gt_elem):
                comparisons.append(normalize_number_str(ma_elem) == float(gt_elem))
            else:
                # 원소 비교는 구두점을 남긴다. 목록 원소에 구두점이 뜻을 가질 수 있다(공식 주석 그대로)
                comparisons.append(normalize_str(ma_elem, remove_punct=False)
                                   == normalize_str(gt_elem, remove_punct=False))
        return all(comparisons)
    return normalize_str(model_answer) == normalize_str(ground_truth)


def parse_final_answer(text: str) -> str | None:
    """마지막 `FINAL ANSWER:` 뒤의 한 줄. 없으면 넘침 정리문의 '지금까지의 답' 줄, 그것도 없으면 None.

    공식 scorer 는 제출된 답 문자열만 받는다. 답 추출은 제출자 몫이라, 마크다운 굵게와 백틱,
    템플릿을 그대로 베낀 바깥 대괄호 한 쌍만 벗긴다.
    """
    found = FINAL_ANSWER.findall(text or "") or SUMMARY_ANSWER.findall(text or "")
    if not found:
        return None
    raw = str(found[-1]).strip().strip("*`").strip()
    if raw.startswith("[") and raw.endswith("]") and raw.count("[") == 1:
        raw = raw[1:-1].strip()
    return raw
