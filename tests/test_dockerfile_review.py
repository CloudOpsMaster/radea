"""Dockerfile review: each rule has a trigger and the safe patterns stay quiet."""

import json
import textwrap

import pytest
from click.testing import CliRunner

from radea.cli import main
from radea.static_review.catalog import CATALOG
from radea.static_review.runner import run_dockerfile

LIMIT = 8 * 1024 * 1024
DIGEST = "@sha256:" + "a" * 64
CLEAN = f'FROM python:3.12.4{DIGEST}\nUSER 10001\nCMD ["python", "-V"]\n'


def review(tmp_path, text, name="Dockerfile"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text))
    return run_dockerfile([str(path)], LIMIT)


def rules_in(report):
    return {f["rule"] for f in report["findings"]}


CASES = {
    "DF001": "FROM ubuntu:latest\nUSER 1000\n",
    "DF002": f'FROM python:3.12{DIGEST}\nCMD ["x"]\n',
    "DF003": CLEAN + "ENV DB_PASSWORD=hunter2hunter2\n",
    "DF004": CLEAN + "RUN curl -sSL https://example.invalid/i.sh | bash\n",
    "DF005": CLEAN + "RUN apt-get update && apt-get install -y curl\n",
    "DF006": (
        f"FROM debian:12{DIGEST}\n"
        "RUN apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*\n"
        "USER 1000\n"
    ),
    "DF007": CLEAN + "COPY . /app\nRUN pip install --no-cache-dir -r /app/requirements.txt\n",
    "DF008": CLEAN + "RUN chmod 777 /app\n",
    "DF009": "FROM python:3.12.4\nUSER 1000\n",
}


def test_clean_dockerfile_is_quiet(tmp_path):
    assert review(tmp_path, CLEAN)["findings"] == []


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_fires(tmp_path, rule):
    report = review(tmp_path, CASES[rule])
    assert rule in rules_in(report), (rule, sorted(rules_in(report)))


def test_every_dockerfile_rule_has_a_case():
    assert set(CASES) == {k for k in CATALOG if k.startswith("DF")}


def test_examples():
    assert run_dockerfile(["examples/docker/Dockerfile.good"], LIMIT)["findings"] == []
    bad = run_dockerfile(["examples/docker/Dockerfile.bad"], LIMIT)
    assert {"DF001", "DF002", "DF003", "DF004", "DF008"} <= rules_in(bad)


@pytest.mark.parametrize(
    "text",
    [
        "FROM scratch\nUSER 1\n",
        f"FROM golang:1.22{DIGEST} AS build\nRUN go build ./...\nFROM build AS test\nUSER 1\n",
        "ARG BASE=python:3.12\nFROM ${BASE}\nUSER 1\n",
        CLEAN + "ENV DB_PASSWORD_FILE=/run/secrets/db\nENV PATH=/opt/bin:$PATH\n",
        CLEAN + "# curl x | sh in a comment\n",
        CLEAN + "RUN --mount=type=secret,id=tok pip install --no-cache-dir x\n",
    ],
)
def test_safe_patterns_do_not_fire(tmp_path, text):
    found = rules_in(review(tmp_path, text))
    assert not found - {"DF009"}, found  # an unpinned digest is the only tolerated note


def test_line_continuations_and_numbers(tmp_path):
    text = CLEAN + "RUN apt-get update \\\n    && apt-get install -y curl\n"
    report = review(tmp_path, text)
    finding = next(f for f in report["findings"] if f["rule"] == "DF005")
    assert finding["line"] == 4 and "apt-get" in finding["evidence"]


def test_secret_values_are_never_printed(tmp_path):
    report = review(
        tmp_path, CLEAN + "ENV API_TOKEN=supersecretvalue123\nARG DB_PASSWORD=abc12345\n"
    )
    blob = json.dumps(report)
    assert "supersecretvalue123" not in blob and "abc12345" not in blob
    assert "DF003" in rules_in(report)


def test_dockerfile_variants_are_collected_from_directories(tmp_path):
    (tmp_path / "Dockerfile.prod").write_text("FROM x:latest\n")
    (tmp_path / "app.dockerfile").write_text("FROM x:latest\n")
    (tmp_path / "notes.txt").write_text("FROM x:latest\n")
    report = run_dockerfile([str(tmp_path)], LIMIT)
    assert report["summary"]["files"] == 2


def test_cli_exit_codes(tmp_path):
    runner = CliRunner()
    assert (
        runner.invoke(main, ["dockerfile-review", "examples/docker/Dockerfile.good"]).exit_code == 0
    )
    assert (
        runner.invoke(main, ["dockerfile-review", "examples/docker/Dockerfile.bad"]).exit_code == 2
    )
    result = runner.invoke(main, ["dockerfile-review", "-"], input="FROM a:latest\n")
    assert result.exit_code == 2
    assert runner.invoke(main, ["dockerfile-review", str(tmp_path)]).exit_code == 1
