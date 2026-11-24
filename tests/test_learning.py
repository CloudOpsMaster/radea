import json

from click.testing import CliRunner

from radea.cli import main


def test_readiness_exercise_starter_and_corrected_submission(tmp_path):
    runner = CliRunner()
    starter = runner.invoke(main, ["learn-readiness", "start"])
    assert starter.exit_code == 0
    submission = tmp_path / "exercise.yaml"
    submission.write_text(starter.output)
    arguments = ["learn-readiness", "check", str(submission)]
    result = runner.invoke(main, arguments)
    assert result.exit_code == 2, result.output
    assert not json.loads(result.output)["checks"]["readiness_rule"]
    submission.write_text(
        starter.output
        + """
          readinessProbe:
            httpGet:
              path: /ready
              port: 8080
""".lstrip("\n")
    )
    result = runner.invoke(main, arguments)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["passed"]
    submission.write_text("apiVersion: v1\nkind: Pod\n")
    assert runner.invoke(main, arguments).exit_code == 1
