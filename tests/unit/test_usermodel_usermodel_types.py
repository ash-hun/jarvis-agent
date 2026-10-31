"""usermodel: usermodel_types 의 사용자 모델이 비면 빈 블록을, 있으면 요약과 특성을 담은 프롬프트 블록을 내는지 검증."""

from jarvis.agent_layer.usermodel import UserModel


def test_empty_model_context_is_blank():
    assert UserModel().is_empty() is True
    assert UserModel().as_context() == ""


def test_as_context_includes_summary_and_traits():
    block = UserModel(summary="간결한 답을 선호", traits=["Python 사용", "테스트 중시"]).as_context()

    assert "[사용자 모델]" in block
    assert "간결한 답" in block
    assert "Python 사용" in block and "테스트 중시" in block
