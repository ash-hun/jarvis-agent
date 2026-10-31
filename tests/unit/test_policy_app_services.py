"""policy: AppServices.with_security 가 파이프라인과 sandbox 만 바꾼 사본을 주고 원본은 그대로 두는지 검증한다."""

import dataclasses
from unittest.mock import MagicMock

from jarvis.app.app_services import AppServices


def _services() -> AppServices:
    return AppServices(
        pipeline=MagicMock(name="pipeline"),
        plugin_runner=MagicMock(),
        skill_registry=MagicMock(),
        sandbox=MagicMock(name="sandbox"),
        approval_rules=MagicMock(),
        memory=MagicMock(),
        model_config=MagicMock(),
        activity_clock=MagicMock(),
        openloop_store=MagicMock(),
    )


def test_with_security_swaps_only_pipeline_and_sandbox():
    original = _services()
    pipeline, sandbox = MagicMock(), MagicMock()
    copy = original.with_security(pipeline, sandbox)

    assert copy is not original
    assert copy.pipeline is pipeline and copy.sandbox is sandbox
    for f in dataclasses.fields(AppServices):
        if f.name not in ("pipeline", "sandbox"):
            assert getattr(copy, f.name) is getattr(original, f.name), f.name


def test_with_security_leaves_original_untouched_and_repeats_the_same():
    original = _services()
    before = (original.pipeline, original.sandbox)
    pipeline, sandbox = MagicMock(), MagicMock()
    first = original.with_security(pipeline, sandbox)
    second = original.with_security(pipeline, sandbox)
    assert (original.pipeline, original.sandbox) == before
    assert first == second
