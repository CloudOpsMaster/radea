"""Smoke tests for CLI commands (no LLM calls)."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from radea.cli import main


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def sample_log(tmp_path: Path) -> Path:
    p = tmp_path / "ci.log"
    p.write_text("ERROR: ModuleNotFoundError: No module named 'boto3'\nFailed to run tests")
    return p


@pytest.fixture()
def sample_tf(tmp_path: Path) -> Path:
    p = tmp_path / "main.tf"
    p.write_text(
        'resource "aws_iam_role" "lambda" {\n'
        '  assume_role_policy = jsonencode({"Action": "*", "Resource": "*"})\n'
        "}\n"
    )
    return p


def test_version(runner):
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    from radea import __version__

    assert f"radea, version {__version__}" in result.output


def test_debug_requires_log(runner):
    result = runner.invoke(main, ["debug"])
    assert result.exit_code != 0


def test_iac_review_requires_file_or_plan(runner):
    result = runner.invoke(main, ["iac-review"])
    assert result.exit_code != 0


def test_debug_sanitizes_secrets(runner, sample_log: Path, monkeypatch):
    """Sanitizer strips secrets before the LLM call (LLM is mocked)."""
    from unittest.mock import patch

    sample_log.write_text("token=AKIAIOSFODNN7EXAMPLE build failed")

    fake_result = {
        "category": "unknown",
        "hypotheses": [],
        "sanitizer": {"redactions": 1},
    }
    with patch("radea.core.llm.call", return_value=fake_result):
        result = runner.invoke(main, ["debug", "--log", str(sample_log), "--output", "json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["sanitizer"]["redactions"] >= 1


def test_post_comment_missing_file(runner):
    result = runner.invoke(main, ["post-comment", "nonexistent.json"])
    assert result.exit_code != 0
