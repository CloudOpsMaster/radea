import json

import pytest
from click.testing import CliRunner

from radea.cli import main


def test_ci_graph_expands_nested_local_includes(tmp_path):
    pipeline = tmp_path / ".gitlab-ci.yml"
    pipeline.write_text("include: [inner.yml, overrides.yml]\nverify:\n  needs: [package]\n")
    (tmp_path / "nested.yml").write_text("package:\n  stage: build\n  script: make\n")
    (tmp_path / "inner.yml").write_text(
        "include: {local: /nested.yml}\nverify:\n  needs: [older]\n  script: test\n"
    )
    (tmp_path / "overrides.yml").write_text("verify:\n  needs: [override]\n")
    runner = CliRunner()
    args = ["ci-graph", str(pipeline), "--gitlab-root", str(tmp_path)]
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["order"] == ["package", "verify"]
    assert report["resolved_local_includes"] == 3
    assert not report["partial"]

    (tmp_path / "nested.yml").write_text(
        "include: 'https://example.invalid/remote.yml'\npackage:\n  stage: build\n  script: make\n"
    )
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["partial"]
    (tmp_path / "nested.yml").write_text("include: inner.yml\n")
    result = runner.invoke(main, args)
    assert result.exit_code == 1
    assert "include cycle" in result.output
    (tmp_path / "nested.yml").write_text("include: ../outside.yml\n")
    result = runner.invoke(main, args)
    assert result.exit_code == 1
    assert "escapes the repository root" in result.output


def test_ci_graph_resolves_nested_templates_and_diff_compares_effective_edges(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    for root in (before, after):
        root.mkdir()
        (root / ".gitlab-ci.yml").write_text(
            "include: templates.yml\n"
            "build:\n  stage: build\n"
            "lint:\n  stage: build\n"
            "verify:\n  extends: [.base, .override]\n"
            "early:\n  extends: .base\n  needs: []\n"
        )
        (root / "templates.yml").write_text(
            ".base:\n  stage: deploy\n  needs: [build, lint]\n"
            ".override:\n  extends: .nested\n"
            ".nested:\n  needs: [" + ("build" if root == before else "lint") + "]\n"
        )
    runner = CliRunner()
    paths = [str(root / ".gitlab-ci.yml") for root in (before, after)]
    result = runner.invoke(main, ["ci-graph", paths[0], "--gitlab-root", str(before)])
    assert result.exit_code == 0, result.output
    graph = json.loads(result.output)
    assert graph["partial"] is False
    jobs = {job["name"]: job for job in graph["jobs"]}
    assert set(jobs) == {"early", "build", "lint", "verify"}
    assert jobs["verify"]["needs"] == ["build"]
    assert jobs["verify"]["stage"] == "deploy"
    assert jobs["early"]["needs"] == []
    assert jobs["early"]["mode"] == "explicit"
    result = runner.invoke(main, [
        "ci-diff", *paths, "--before-gitlab-root", str(before), "--after-gitlab-root", str(after),
        "--fail-on-change",
    ])
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert not report["partial"]
    (changed,) = report["modified"]
    assert changed["name"] == "verify"
    assert changed["before"]["needs"] == ["build"]
    assert changed["after"]["needs"] == ["lint"]


@pytest.mark.parametrize(("source", "marker"), [
    ("job: {extends: .missing}", ".missing"),
    ("job: {extends: .base}\n.base: {rules: [{when: manual}]}", None),
])
def test_ci_graph_preserves_uncertainty_in_inherited_graphs(source, marker):
    result = CliRunner().invoke(main, ["ci-graph", "-"], input=source)
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["partial"]
    assert report["unresolved_extends"] == ([marker] if marker else [])


def test_ci_graph_rejects_extends_cycles_and_excessive_depth():
    runner = CliRunner()
    result = runner.invoke(
        main, ["ci-graph", "-"], input="job: {extends: .base}\n.base: {extends: job}",
    )
    assert result.exit_code == 1
    assert "inheritance cycle" in result.output

    # Resolve the shorter path first to exercise the cached-depth check.
    chain = "".join(f".p{i}: {{extends: .p{i + 1}}}\n" for i in range(11))
    chain += ".p11: {}\nshort: {extends: .p1}\nlong: {extends: .p0}\n"
    result = runner.invoke(main, ["ci-graph", "-"], input=chain)
    assert result.exit_code == 1
    assert "eleven inheritance levels" in result.output
