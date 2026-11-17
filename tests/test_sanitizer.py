"""Tests for core.sanitizer."""

from radea.core.sanitizer import REDACT, sanitize


def test_aws_access_key():
    text = "key=AKIAIOSFODNN7EXAMPLE rest"
    r = sanitize(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in r.text
    assert REDACT in r.text
    assert r.redactions >= 1
    assert "aws_key" in r.types_found


def test_github_pat():
    text = "token: ghp_abcdefghijklmnopqrstuvwxyz123456"
    r = sanitize(text)
    assert "ghp_" not in r.text
    assert r.redactions >= 1


def test_url_password():
    text = "connecting to https://admin:s3cr3t@db.internal/prod"
    r = sanitize(text)
    assert "s3cr3t" not in r.text
    assert "https://admin:" in r.text  # prefix kept
    assert "db.internal" not in r.text  # internal identifiers are now private


def test_generic_token():
    text = "api_key=supersecretvalue1234567890"
    r = sanitize(text)
    assert "supersecretvalue" not in r.text
    assert r.redactions >= 1


def test_clean_text_unchanged():
    text = "Build failed: ModuleNotFoundError: No module named 'requests'"
    r = sanitize(text)
    assert r.text == text
    assert r.redactions == 0


def test_multiple_secrets():
    text = "token=abc123def456ghi789 and password=xyz987abc654def321"
    r = sanitize(text)
    assert r.redactions >= 2


def test_pem_block():
    text = "key:\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAK\n-----END RSA PRIVATE KEY-----\n"
    r = sanitize(text)
    assert "PRIVATE KEY" not in r.text
    assert r.redactions >= 1
