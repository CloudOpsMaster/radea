import json
from unittest.mock import patch

from click.testing import CliRunner

from radea.cli import main
from radea.core.config import Config
from radea.core.diagnostics import readiness


def test_doctor_never_prints_key_or_claims_authentication():
    with patch("radea.core.diagnostics.importlib.util.find_spec", return_value=object()):
        result = readiness(Config(openai_api_key="synthetic-secret-value"))
    assert result["configured"] is True
    assert result["authentication_verified"] is False
    assert "synthetic-secret-value" not in json.dumps(result)


def test_doctor_missing_key_never_contacts_provider(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("radea.core.llm.call") as model:
        result = CliRunner().invoke(main, ["doctor", "--output", "json"])
    model.assert_not_called()
    assert result.exit_code == 1
    assert json.loads(result.output)["inference_tested"] is False


def test_kiro_session_is_unknown_until_live_probe():
    with patch("radea.core.diagnostics.shutil.which", return_value="/mock/kiro-cli"):
        result = readiness(Config(model="kiro"))
    assert result["credential_present"] is None and result["configured"]
    assert result["authentication_verified"] is False


def test_smoke_requires_explicit_live_flag():
    with patch("radea.core.llm.call") as model:
        result = CliRunner().invoke(main, ["smoke"])
    assert result.exit_code != 0
    model.assert_not_called()


def test_live_smoke_missing_auth_is_reported_without_inference(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with patch("radea.core.llm.call") as model:
        result = CliRunner().invoke(main, ["smoke", "--live", "--output", "json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["inference_attempted"] is False
    model.assert_not_called()


def test_smoke_uses_guarded_analysis_not_unvalidated_sdk_result(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    with patch("radea.core.llm.call", return_value={"unrelated": 123}):
        result = CliRunner().invoke(main, ["smoke", "--live", "--output", "json"])
    assert json.loads(result.output)["status"] == "failed"


def test_quota_code_is_safe_and_not_retryable():
    from radea.core import llm

    failure = RuntimeError("DO NOT DISCLOSE synthetic-secret-value")
    failure.code = "insufficient_quota"
    failure.status_code = 429
    with patch("radea.core.llm._call_openai", side_effect=failure):
        result = llm.call(system="s", user="u", cfg=Config(openai_api_key="dummy"))
    assert result["provider_error_code"] == "insufficient_quota"
    assert result["http_status"] == 429 and result["retryable"] is False
    assert "synthetic-secret-value" not in json.dumps(result)


def test_unknown_error_codes_and_messages_are_not_forwarded():
    from radea.core.provider_errors import details, public_details

    failure = RuntimeError("private")
    failure.code = "private-credential-value"
    assert "private-credential-value" not in json.dumps(details(failure))
    result = public_details(
        {
            "provider_error_code": "private-credential-value",
            "remediation": "private",
            "http_status": "private",
        }
    )
    assert result == {}


def test_quota_diagnostics_survive_guarded_smoke(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    with patch(
        "radea.core.llm.call",
        return_value={
            "error": "Provider failed",
            "provider_error_code": "insufficient_quota",
            "http_status": 429,
        },
    ):
        result = CliRunner().invoke(main, ["smoke", "--live", "--output", "json"])
    report = json.loads(result.output)
    assert report["provider_error_code"] == "insufficient_quota"
    assert report["retryable"] is False


def test_current_billing_codes_are_allowlisted_without_forwarding_advice():
    from radea.core.provider_errors import public_details

    for code in (
        "credit_balance_exhausted",
        "project_spend_limit_exceeded",
        "organization_spend_limit_exceeded",
        "organization_usage_limit_exceeded",
    ):
        result = public_details({"provider_error_code": code, "remediation": "private credential"})
        assert result["provider_error_code"] == code and result["retryable"] is False
        assert "private credential" not in json.dumps(result)
    assert public_details({"provider_error_code": []}) == {}


def test_missing_provider_code_can_be_classified_without_exposing_message():
    from radea.core.provider_errors import details

    failure = RuntimeError()
    failure.message = "You exceeded your current quota. secret=DO_NOT_PUBLISH"
    result = details(failure)
    assert result["provider_error_category"] == "quota_exhausted"
    assert result["retryable"] is False
    assert "DO_NOT_PUBLISH" not in json.dumps(result)
    failure.message = "unrecognized private response"
    failure.type = "insufficient_quota"
    assert details(failure)["retryable"] is False
