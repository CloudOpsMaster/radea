import json

from click.testing import CliRunner

from radea.cli import main


def test_shell_parity_executes_scenarios_without_reporting_output(tmp_path):
    baseline = tmp_path / "baseline.sh"
    candidate = tmp_path / "candidate.sh"
    cases = tmp_path / "cases.json"
    baseline.write_text('printf "%s\\n" "$1"\ncat\n')
    candidate.write_text('printf "%s\\n" "$@"\ncat\n')
    cases.write_text(
        json.dumps(
            [
                {"id": "one", "args": ["one space"], "stdin": "PRIVATE_OUTPUT"},
                {"id": "two", "args": ["one space", "another"]},
            ]
        )
    )
    args = ["shell-parity", str(baseline), str(candidate), str(cases), "--execute"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 2
    assert "PRIVATE_OUTPUT" not in result.output
    cases_result = json.loads(result.output)["cases"]
    assert [case["differences"] for case in cases_result] == [[], ["stdout"]]
    candidate.write_text(baseline.read_text())
    assert CliRunner().invoke(main, args).exit_code == 0
