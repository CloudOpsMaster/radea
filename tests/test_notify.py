"""Tests for notify.comment markdown rendering."""

import pytest

from radea.notify.comment import _md_debug, _md_iac

_DEBUG_RESULT = {
    "category": "dependency_drift",
    "hypotheses": [
        {
            "title": "Package version bump",
            "confidence": "high",
            "description": "axios bumped 1.x to 2.x breaking the import.",
            "verify": "git log --oneline package-lock.json | head -5",
        }
    ],
    "sanitizer": {"redactions": 2},
}

_IAC_RESULT = {
    "summary": "Provisions a Lambda function and an S3 bucket.",
    "destructive_actions": [{"resource": "aws_rds_instance.main", "action": "destroy"}],
    "findings": [
        {
            "severity": "high",
            "title": "IAM role too permissive",
            "resource": "aws_iam_role.exec",
            "description": 'Action "*" on Resource "*" should be scoped down.',
        }
    ],
}


def test_md_debug_contains_category():
    md = _md_debug(_DEBUG_RESULT)
    assert "dependency_drift" in md
    assert "Package version bump" in md
    assert "high" in md
    assert "2 redaction" in md


def test_md_debug_table_format():
    md = _md_debug(_DEBUG_RESULT)
    assert "|" in md  # markdown table
    assert "Verify" in md


def test_md_iac_destructive_banner():
    md = _md_iac(_IAC_RESULT)
    assert "STOP" in md
    assert "aws_rds_instance.main" in md
    assert "destroy" in md


def test_md_iac_findings():
    md = _md_iac(_IAC_RESULT)
    assert "IAM role too permissive" in md
    assert "🔴" in md


def test_md_iac_summary():
    md = _md_iac(_IAC_RESULT)
    assert "Lambda function" in md


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http://example.test", "https://u:p@example.test"]
)
def test_comment_rejects_unsafe_url(url):
    from radea.notify.comment import _http_post

    with pytest.raises(ValueError, match="HTTPS"):
        _http_post(url, {}, {})
