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


# --- Secret formats that previously passed through (fake values built at runtime so that
# --- the repository never contains token-shaped literals that trip push protection).
_TAIL = "AbCdEfGhIjKlMnOpQrStUvWx12"
_JWT = "ey" + "JhbGciOiJIUzI1NiJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0." + "c2lnbmF0dXJlLXZhbHVlLTEyMw"


def _leaks(text: str, secret: str) -> bool:
    return secret in sanitize(text).text


def test_gitlab_tokens_without_key_name():
    for prefix in ("gl" + "pat-", "gl" + "dt-", "gl" + "rt-", "gl" + "cbt-", "gl" + "ptt-"):
        secret = prefix + _TAIL
        assert not _leaks(f"using {secret} for api", secret), prefix


def test_jwt_without_key_name():
    assert not _leaks(f"session {_JWT} ok", _JWT)


def test_slack_stripe_npm_pypi_google_sendgrid_tokens():
    secrets = [
        "xox" + "b-123456789012-1234567890123-" + _TAIL,
        "sk_" + "live_" + _TAIL,
        "rk_" + "test_" + _TAIL,
        "npm_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
        "pypi-" + "AgEIcHlwaS5vcmc" + _TAIL + "_-",
        "ya" + "29." + _TAIL + "-_",
        "SG" + "." + _TAIL + "." + _TAIL,
        "dckr_" + "pat_" + _TAIL,
    ]
    for secret in secrets:
        assert not _leaks(f"value {secret} end", secret), secret


def test_netrc_password_without_separator():
    one_line = "machine host.example.org login someone password S3cr3tP4ss"
    assert "S3cr3tP4ss" not in sanitize(one_line).text
    multi = "machine host.example.org\n  login someone\n  password S3cr3tP4ss\n"
    assert "S3cr3tP4ss" not in sanitize(multi).text


def test_plain_words_after_password_are_kept():
    text = "authentication failed: password required for user"
    assert sanitize(text).text == text


def test_cloud_connection_string_and_kubeconfig_keys():
    azure = "AccountName=foo;AccountKey=" + _TAIL + "+/" + _TAIL + "==;EndpointSuffix=x"
    assert _TAIL not in sanitize(azure).text
    sas = "SharedAccessKey=" + _TAIL + "+/" + _TAIL + "="
    assert _TAIL not in sanitize(sas).text
    kube = "    client-key-data: " + "LS0tLS1CRUdJTiBSU0Eg" + _TAIL
    assert _TAIL not in sanitize(kube).text
    assert _TAIL not in sanitize('"private_key": "' + _TAIL + '"').text


def test_invisible_and_fullwidth_obfuscation_is_stripped():
    assert "hunter2" not in sanitize("pass\u200bword=hunter2").text
    assert "hunter2" not in sanitize("pass\u2060word: hunter2").text
    fullwidth = "\uff50\uff41\uff53\uff53\uff57\uff4f\uff52\uff44=hunter2"
    assert "hunter2" not in sanitize(fullwidth).text


def test_configurable_internal_domains(monkeypatch):
    text = "fetch https://gerrit.corp-example.net/a/x failed"
    assert sanitize(text).text == text
    monkeypatch.setenv("RADEA_INTERNAL_DOMAINS", "corp-example.net, other.example")
    redacted = sanitize(text).text
    assert "corp-example.net" not in redacted
    assert "[HOST_" in redacted


def test_clean_redacts_sensitive_key_names_in_json():
    from radea.core.sanitizer import clean

    value = {"clientSecret": "abc", "account_key": "def", "max_tokens": 5, "note": "ok"}
    out = clean(value)
    assert out["clientSecret"] == REDACT and out["account_key"] == REDACT
    assert out["max_tokens"] == 5 and out["note"] == "ok"


def test_internal_suffix_not_matched_inside_longer_label():
    text = "fetch https://gerrit.corp-example.net/a failed and svc.local-dev.example.org"
    assert sanitize(text).text == text
    assert "[HOST_1]" in sanitize("connect svc.cluster.local refused").text
