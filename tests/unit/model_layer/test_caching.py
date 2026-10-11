"""Anthropic Prompt Caching: _inject_cache_breakpoint 단위 테스트."""
from __future__ import annotations

from jarvis.model_layer.providers.anthropic import _inject_cache_breakpoint


class TestInjectCacheBreakpoint:
    def test_no_op_on_single_message(self):
        messages = [{"role": "user", "content": "hello"}]
        _inject_cache_breakpoint(messages)
        assert "cache_control" not in str(messages)

    def test_adds_cache_control_to_second_to_last(self):
        messages = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
            {"role": "user", "content": [{"type": "text", "text": "again"}]},
        ]
        _inject_cache_breakpoint(messages)
        # messages[-2] = assistant turn, 마지막 content block에 cache_control 삽입
        last_block = messages[-2]["content"][-1]
        assert last_block["cache_control"] == {"type": "ephemeral"}
        # 현재 user 입력(messages[-1])은 캐시하지 않음
        assert "cache_control" not in str(messages[-1])

    def test_converts_string_content_to_list(self):
        """content가 str일 때 list로 변환 후 cache_control 추가."""
        messages = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]
        _inject_cache_breakpoint(messages)
        assert isinstance(messages[-2]["content"], list)
        assert messages[-2]["content"][-1]["cache_control"] == {"type": "ephemeral"}

    def test_no_op_on_empty_list_content(self):
        messages = [
            {"role": "user", "content": []},
            {"role": "user", "content": "current"},
        ]
        _inject_cache_breakpoint(messages)
        # content가 빈 리스트면 수정 없음
        assert messages[-2]["content"] == []
