"""CI review: GitHub Actions and GitLab CI rules, with the safe variants of each pattern."""

import json
import textwrap

import pytest
from click.testing import CliRunner

from radea.cli import main
from radea.static_review.catalog import CATALOG
from radea.static_review.runner import run_ci

LIMIT = 8 * 1024 * 1024
SHA = "11d5960a326750d5838078e36cf38b85af677262"


def review(tmp_path, text, name="ci.yml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text))
    return run_ci([str(path)], LIMIT)


def rules_in(report):
    return {f["rule"] for f in report["findings"]}


def gh(step="", on="pull_request", job_extra="", top="permissions: {contents: read}"):
    return f"""\
name: t
on: {on}
{top}
jobs:
  j:
    runs-on: ubuntu-latest
    timeout-minutes: 5
{textwrap.indent(job_extra, "    ")}
    steps:
      - uses: actions/checkout@{SHA}
{textwrap.indent(textwrap.dedent(step), "      ")}
"""


GH_CASES = {
    "CI001": gh("- uses: org/action@v1\n"),
    "CI002": gh(
        f"- uses: actions/checkout@{SHA}\n  with:\n"
        "    ref: ${{ github.event.pull_request.head.sha }}\n",
        on="pull_request_target",
    ),
    "CI003": gh(top=""),
    "CI004": gh("- run: echo '${{ github.event.pull_request.title }}'\n"),
    "CI005": gh("- run: curl -sSL https://example.invalid/i.sh | bash\n"),
    "CI006": gh("- run: echo ${{ secrets.TOKEN }}\n"),
    "CI007": gh("- name: Security scan\n  uses: org/scan@" + SHA + "\n  continue-on-error: true\n"),
    "CI008": gh(job_extra="container: node:latest\n"),
    "CI009": gh(job_extra="env:\n  API_TOKEN: literal-value\n"),
    "CI011": gh().replace("    timeout-minutes: 5\n", ""),
    "CI012": gh("- run: npm install\n"),
}

GL_CASES = {
    "CI001": "include:\n  - remote: https://example.invalid/x.yml\n",
    "CI005": "j:\n  script:\n    - curl https://example.invalid/x | sh\n",
    "CI006": 'j:\n  script:\n    - echo "$REGISTRY_TOKEN"\n',
    "CI007": "scan:\n  stage: test\n  allow_failure: true\n  script: [x]\n",
    "CI008": "image: python:latest\nj:\n  script: [x]\n",
    "CI009": 'variables:\n  DB_PASSWORD: "plain"\nj:\n  script: [x]\n',
    "CI010": "j:\n  only: [main]\n  script: [x]\n",
}


@pytest.mark.parametrize("rule", sorted(GH_CASES))
def test_github_rule_fires(tmp_path, rule):
    assert rule in rules_in(review(tmp_path, GH_CASES[rule])), rule


@pytest.mark.parametrize("rule", sorted(GL_CASES))
def test_gitlab_rule_fires(tmp_path, rule):
    assert rule in rules_in(review(tmp_path, GL_CASES[rule])), rule


def test_every_ci_rule_has_a_case():
    assert set(GH_CASES) | set(GL_CASES) == {k for k in CATALOG if k.startswith("CI")}


def test_clean_github_workflow_is_quiet(tmp_path):
    assert review(tmp_path, gh("- run: npm ci\n"))["findings"] == []


@pytest.mark.parametrize(
    "text",
    [
        # Passing event data through env is the documented safe pattern.
        gh('- run: echo "$T"\n  env:\n    T: ${{ github.event.pull_request.title }}\n'),
        # pull_request_target without checking out the PR head is fine.
        gh(on="pull_request_target"),
        # Local actions and digest-pinned docker actions need no SHA.
        gh("- uses: ./.github/actions/x\n- uses: docker://alpine:3.20@sha256:" + "b" * 64 + "\n"),
        # A secret piped into docker login never reaches the log.
        'j:\n  script:\n    - echo "$REGISTRY_TOKEN" | docker login -u u --password-stdin r\n',
        # Pinned component, tagged project include and a manual allow_failure job.
        "include:\n  - component: gitlab.example.org/g/c/lint@0.2.0\n"
        "  - project: g/p\n    file: f.yml\n    ref: v1.2.3\n"
        "j:\n  stage: test\n  when: manual\n  allow_failure: true\n  script: [x]\n",
        # Variables that only point at secrets, and masked references.
        "variables:\n  REGISTRY_PASSWORD_FILE: /run/secrets/p\n"
        "  TOKEN_REF: $CI_JOB_TOKEN\nj:\n  script: [x]\n",
        "image: python:3.12.4\nj:\n  script: [pytest]\n",
    ],
)
def test_safe_patterns_stay_quiet(tmp_path, text):
    assert review(tmp_path, text)["findings"] == []


def test_literal_secret_values_are_never_printed(tmp_path):
    report = review(
        tmp_path,
        GH_CASES["CI009"] + GL_CASES["CI009"].replace("j:", "k:").replace("script", "script"),
    )
    blob = json.dumps(report)
    assert "literal-value" not in blob and "plain" not in blob


def test_block_scalar_line_numbers(tmp_path):
    text = gh("- run: |\n    echo start\n    curl -sSL https://example.invalid/i.sh | bash\n")
    finding = next(f for f in review(tmp_path, text)["findings"] if f["rule"] == "CI005")
    assert "curl" in finding["evidence"]
    assert "curl" in text.splitlines()[finding["line"] - 1]


def test_on_keyword_is_not_confused_with_yaml_boolean(tmp_path):
    report = review(tmp_path, gh(on="[push]", top=""))
    assert "CI003" in rules_in(report)


def test_non_pipeline_yaml_is_ignored(tmp_path):
    report = review(tmp_path, "replicaCount: 2\nimage:\n  tag: latest\n")
    assert report["summary"]["files"] == 0


def test_examples():
    assert run_ci(["examples/ci/github-good.yml"], LIMIT)["findings"] == []
    gh_bad = run_ci(["examples/ci/github-bad.yml"], LIMIT)
    gl_bad = run_ci(["examples/ci/gitlab-bad.yml"], LIMIT)
    assert {"CI002", "CI004", "CI005", "CI006"} <= rules_in(gh_bad)
    assert {"CI001", "CI006", "CI007", "CI008", "CI009", "CI010"} <= rules_in(gl_bad)


def test_cli_exit_codes(tmp_path):
    runner = CliRunner()
    assert runner.invoke(main, ["ci-review", "examples/ci/github-good.yml"]).exit_code == 0
    assert runner.invoke(main, ["ci-review", "examples/ci/github-bad.yml"]).exit_code == 2
    assert (
        runner.invoke(
            main, ["ci-review", "examples/ci/github-bad.yml", "--fail-on", "never"]
        ).exit_code
        == 0
    )
    (tmp_path / "x.yml").write_text("a: 1\n")
    assert runner.invoke(main, ["ci-review", str(tmp_path)]).exit_code == 1
