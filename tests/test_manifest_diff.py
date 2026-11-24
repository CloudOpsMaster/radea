import json

from click.testing import CliRunner

from radea.cli import main

SECRET = """\
apiVersion: v1
kind: Secret
metadata: {name: demo}
stringData:
  on: first-demo-value
  off: fixed
"""


def test_diff_reports_fields_and_never_values(tmp_path):
    before = tmp_path / "before.yaml"
    before.write_text(SECRET)
    after = SECRET.replace("first-demo-value", "second-demo-value")
    result = CliRunner().invoke(
        main,
        ["manifest-diff", str(before), "-", "--output", "json", "--fail-on-change"],
        input=after,
    )
    assert result.exit_code == 2
    assert "demo-value" not in result.output
    assert json.loads(result.output)["changes"] == [
        {
            "group": "",
            "kind": "Secret",
            "namespace": "",
            "name": "demo",
            "action": "modified",
            "fields": ["stringData"],
        }
    ]


def test_diff_ignores_key_and_document_order(tmp_path):
    before = tmp_path / "before.yaml"
    service = "apiVersion: v1\nkind: Service\nmetadata: {name: demo}\n"
    before.write_text(SECRET + "---\n" + service)
    after = (
        service
        + "---\n"
        + SECRET.replace(
            "  on: first-demo-value\n  off: fixed", "  off: fixed\n  on: first-demo-value"
        )
    )
    result = CliRunner().invoke(main, ["manifest-diff", str(before), "-"], input=after)
    assert result.exit_code == 0
    assert "0 changed" in result.output


def test_diff_rejects_duplicate_resource_and_mapping_keys(tmp_path):
    before = tmp_path / "before.yaml"
    before.write_text(SECRET)
    for after in (SECRET + "---\n" + SECRET, SECRET + "  on: duplicate\n"):
        result = CliRunner().invoke(main, ["manifest-diff", str(before), "-"], input=after)
        assert result.exit_code == 1


def test_malformed_chart_reports_error_instead_of_clean_review(tmp_path):
    chart = tmp_path / "Chart.yaml"
    chart.write_text("name: malformed\ndependencies: 2\n")
    result = CliRunner().invoke(main, ["k8s-review", str(chart)])
    assert result.exit_code == 1
    assert "dependencies must be a list" in result.output
