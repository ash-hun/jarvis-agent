"""[memory] 절차 블록은 설명이 없을 때만 "이름: " 꼬리를 빼고, 설명 끝의 ":" 와 공백은 그대로 둔다."""

from jarvis.memory.memory_service import PROCEDURES_HEADER, _procedures_block
from jarvis.memory.long_term.procedural import Procedure


def test_description_trailing_colon_is_kept():
    procedures = [Procedure(name="deploy", description="다음 순서:"), Procedure(name="bare", description="")]
    block = _procedures_block(procedures)
    assert block.content == f"{PROCEDURES_HEADER}\n- /deploy: 다음 순서:\n- /bare"
