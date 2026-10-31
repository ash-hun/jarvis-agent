"""proactive_eval: 평가 CLI 가 엔진 없이 policy 묶음을 돌려 사람용, JSON 보고서를 내는지 검증한다."""

from jarvis.core.proactive.eval.__main__ import main


def test_cli_runs_policy_suite_offline(capsys):
    codes = [main(["--suite", "policy"]), main(["--json", "--suite", "policy"])]

    assert codes == [0, 0]
    assert '"suites"' in capsys.readouterr().out
