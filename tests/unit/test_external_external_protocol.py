"""external 의 ExternalSource 기본 클래스: 기본 동작과 구현체의 상속을 검증한다."""

from jarvis.core.external import ExternalSource, ExternalSourceSpec, McpToolSource
from jarvis.jarvis_config import MCPServerConfig


async def test_external_source_default_polls_nothing():
    source = ExternalSource("blank", 60.0)

    assert (source.name, source.interval_sec) == ("blank", 60.0)
    assert await source.poll() == []


def test_mcp_source_is_external_source_with_spec_fields():
    spec = ExternalSourceSpec(name="cal", server="gcal", tool="list_events", interval_sec=42.0)

    source = McpToolSource(spec, MCPServerConfig(name="gcal"))

    assert isinstance(source, ExternalSource)
    assert (source.name, source.interval_sec) == ("cal", 42.0)
