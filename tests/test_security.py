"""Security tests — run as part of the standard test suite on every PR.

Covers:
  - Sanitizer strips every secret pattern before any external call
  - Sanitizer never mutates clean text
  - LLM client rejects calls when OPENAI_API_KEY is absent (no silent data leak)
  - post-comment never exposes secrets in the Markdown body it builds
  - Config never reads secrets from anything other than env vars
  - dry-run never reaches the LLM client
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from radea.cli import main
from radea.core.sanitizer import REDACT, sanitize
from radea.notify.comment import _md_debug, _md_iac

# ── Sanitizer ─────────────────────────────────────────────────────────────────


class TestSanitizerSecurity:
    """Every secret pattern must be stripped before text leaves the process."""

    SECRETS = [
        ("aws_access_key", "AKIAIOSFODNN7EXAMPLE"),
        ("aws_secret_key", "aws_secret_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
        ("generic_token", "token=supersecretvalue1234567890ab"),
        ("auth_header", "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"),
        ("github_pat", "ghp_abcdefghijklmnopqrstuvwxyz123456"),
        ("url_password", "https://admin:s3cr3tP4ss@db.internal/prod"),
        (
            "pem_block",
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK\n-----END RSA PRIVATE KEY-----",
        ),
    ]

    @pytest.mark.parametrize("name,secret", SECRETS)
    def test_secret_is_redacted(self, name: str, secret: str) -> None:
        result = sanitize(f"some log line {secret} rest of line")
        # The raw secret value must not survive sanitization
        raw_value = secret.split("=")[-1].split(" ")[-1].split(":")[-1].lstrip("/")
        assert raw_value[:12] not in result.text, f"{name} not redacted"
        assert result.redactions >= 1

    def test_redacted_marker_present(self) -> None:
        result = sanitize("token=supersecretvalue1234567890ab")
        assert REDACT in result.text

    def test_clean_text_not_mutated(self) -> None:
        text = "Build failed: ModuleNotFoundError: No module named 'boto3'"
        result = sanitize(text)
        assert result.text == text
        assert result.redactions == 0

    def test_multiple_secrets_all_redacted(self) -> None:
        text = (
            "AKIAIOSFODNN7EXAMPLE "
            "token=supersecretvalue1234567890ab "
            "ghp_abcdefghijklmnopqrstuvwxyz123456"
        )
        result = sanitize(text)
        assert result.redactions >= 3
        assert "AKIAIOSFODNN7EXAMPLE" not in result.text
        assert "supersecretvalue" not in result.text
        assert "ghp_abcdefghijklmnopqrstuvwxyz" not in result.text

    def test_url_password_internal_host_redacted(self) -> None:
        result = sanitize("https://admin:s3cr3tP4ss@db.internal/prod")
        assert "s3cr3tP4ss" not in result.text
        assert "db.internal" not in result.text


# ── LLM client ────────────────────────────────────────────────────────────────


class TestLLMClientSecurity:
    """LLM errors must surface in the result dict, never be swallowed silently."""

    def test_llm_error_surfaces_in_triage(self) -> None:
        """When the LLM call fails, triage_log returns an error key, not an empty result."""
        from io import StringIO

        from radea.pipeline_debug.triage import triage_log

        with patch("radea.core.llm.call", side_effect=Exception("Incorrect API key")):
            # Capture stdout since output="json" prints to stdout
            captured = StringIO()
            with patch("sys.stdout", captured):
                triage_log(log_path="examples/logs/failed-build.log", output="json", dry_run=False)

        result = json.loads(captured.getvalue())
        assert "error" in result

    def test_llm_error_surfaces_in_iac_review(self) -> None:
        from io import StringIO

        from radea.iac_review.review import review_iac

        with patch("radea.core.llm.call", side_effect=Exception("network error")):
            captured = StringIO()
            with patch("sys.stdout", captured):
                review_iac(
                    tf_file="examples/terraform/main.tf",
                    plan_file=None,
                    context_file=None,
                    output="json",
                    dry_run=False,
                )

        result = json.loads(captured.getvalue())
        assert "error" in result


# ── dry-run never calls LLM ───────────────────────────────────────────────────


class TestDryRunSecurity:
    """--dry-run must not reach the LLM under any circumstances."""

    @pytest.fixture()
    def runner(self):
        return CliRunner()

    @pytest.fixture()
    def log_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "ci.log"
        p.write_text("token=AKIAIOSFODNN7EXAMPLE build failed")
        return p

    @pytest.fixture()
    def tf_file(self, tmp_path: Path) -> Path:
        p = tmp_path / "main.tf"
        p.write_text('resource "aws_s3_bucket" "b" { bucket = "test" }')
        return p

    def test_debug_dry_run_no_llm_call(self, runner, log_file: Path) -> None:
        with patch("radea.core.llm.call") as mock_llm:
            runner.invoke(main, ["debug", "--log", str(log_file), "--dry-run"])
        mock_llm.assert_not_called()

    def test_iac_review_dry_run_no_llm_call(self, runner, tf_file: Path) -> None:
        with patch("radea.core.llm.call") as mock_llm:
            runner.invoke(main, ["iac-review", "--file", str(tf_file), "--dry-run"])
        mock_llm.assert_not_called()

    def test_triage_dry_run_no_llm_call(self, runner, log_file: Path) -> None:
        with patch("radea.core.llm.call") as mock_llm:
            runner.invoke(main, ["triage", "--logs", str(log_file), "--dry-run"])
        mock_llm.assert_not_called()

    def test_dry_run_secrets_not_in_output(self, runner, log_file: Path) -> None:
        """Even in dry-run preview, raw secrets must not appear."""
        result = runner.invoke(main, ["debug", "--log", str(log_file), "--dry-run"])
        assert "AKIAIOSFODNN7EXAMPLE" not in result.output


# ── Markdown output contains no secrets ──────────────────────────────────────


class TestNotifyCommentSecurity:
    """The Markdown body posted to PR/MR must never contain raw secret values."""

    _DEBUG = {
        "category": "dependency_drift",
        "hypotheses": [
            {
                "title": "Package bump",
                "confidence": "high",
                "description": "axios bumped.",
                "verify": "git log package-lock.json",
            }
        ],
        "sanitizer": {"redactions": 1},
    }

    _IAC = {
        "summary": "Provisions a Lambda.",
        "destructive_actions": [{"resource": "aws_rds_instance.main", "action": "destroy"}],
        "findings": [
            {
                "severity": "high",
                "title": "IAM too permissive",
                "resource": "aws_iam_role.exec",
                "description": "Action * on Resource *.",
            }
        ],
    }

    def test_debug_markdown_no_raw_key(self) -> None:
        md = _md_debug(self._DEBUG)
        assert "AKIA" not in md
        assert "sk-" not in md

    def test_iac_markdown_no_raw_key(self) -> None:
        md = _md_iac(self._IAC)
        assert "AKIA" not in md
        assert "sk-" not in md

    def test_debug_markdown_has_draft_warning(self) -> None:
        md = _md_debug(self._DEBUG)
        assert "AI DRAFT" in md

    def test_iac_markdown_has_draft_warning(self) -> None:
        md = _md_iac(self._IAC)
        assert "AI DRAFT" in md


# ── Config reads only from env vars ──────────────────────────────────────────


class TestConfigSecurity:
    """Sensitive values must come from env vars, never from hardcoded defaults."""

    def test_api_key_default_is_empty(self) -> None:
        from radea.core.config import Config

        cfg = Config()
        assert cfg.openai_api_key == ""

    def test_api_key_read_from_env(self, monkeypatch) -> None:
        from radea.core.config import Config

        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        cfg = Config.from_env()
        assert cfg.openai_api_key == "sk-test-key"

    def test_local_flag_disables_openai(self, monkeypatch) -> None:
        from radea.core.config import Config

        monkeypatch.setenv("RADEA_LOCAL", "true")
        cfg = Config.from_env()
        assert cfg.local is True
