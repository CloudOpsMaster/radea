"""Behavioral regressions for the theory audit, including adversarial model output."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from radea.cli import main
from radea.core import llm
from radea.core.config import Config
from radea.core.contracts import ContractError, validate
from radea.core.sanitizer import clean, sanitize
from radea.core.sources import collect


@pytest.mark.parametrize(
    "raw,secret",
    [
        ("password=short-demo", "short-demo"),
        ('{"password":"longdummyvalue123456789"}', "longdummyvalue123456789"),
        ("postgresql://demo:dummy-password@db.internal/demo", "dummy-password"),
        ("redis://default:redis-demo@cache.internal", "redis-demo"),
        ("Authorization: Bearer short-key", "short-key"),
        ("https://example.com/?X-Amz-Signature=demo-signature&x=1", "demo-signature"),
        ("contact=person@example.com", "person@example.com"),
        ("connect 10.1.2.3 db.internal", "db.internal"),
        ("-----BEGIN PRIVATE KEY-----\nDEMO\n-----END PRIVATE KEY-----", "DEMO"),
    ],
)
def test_sensitive_formats(raw, secret):
    result = sanitize(raw)
    assert secret not in result.text
    assert result.redactions > 0


def test_safe_json_structure_and_recursive_clean():
    value = {"password": "small", "items": [{"description": "token=demo"}], "count": 3}
    assert clean(value) == {
        "password": "[REDACTED]",
        "items": [{"description": "token=[REDACTED]"}],
        "count": 3,
    }
    assert (
        sanitize("Build failed: missing module boto3; exit=1").text
        == "Build failed: missing module boto3; exit=1"
    )


def test_large_log_preserves_tail_and_reports_omissions(tmp_path):
    path = tmp_path / "ci.log"
    path.write_text("INFO starting\n" + "INFO working\n" * 5000 + "FATAL final failure\n")
    sources = collect([str(path)], Config())
    assert "FATAL final failure" in sources.records.values()
    assert "INFO starting" in sources.records.values()
    assert sources.truncated
    assert sources.files[0]["omitted_lines"] > 0
    assert len(sources.payload()) < 128000


def test_multiline_key_cannot_leak_through_log_tail(tmp_path):
    path = tmp_path / "ci.log"
    path.write_text(
        "-----BEGIN PRIVATE KEY-----\n"
        + "DEMO_KEY_MATERIAL\n" * 3000
        + "-----END PRIVATE KEY-----\nERROR done\n"
    )
    sources = collect([str(path)], Config())
    assert "DEMO_KEY_MATERIAL" not in sources.payload()
    assert "ERROR done" in sources.records.values()


def test_input_limits_fail_before_model(tmp_path, monkeypatch):
    path = tmp_path / "huge.log"
    path.write_bytes(b"x" * 70000)
    monkeypatch.setenv("RADEA_MAX_INPUT_BYTES", "65536")
    with patch("radea.core.llm.call") as model:
        result = CliRunner().invoke(main, ["debug", "--log", str(path), "--output", "json"])
    assert result.exit_code == 1
    model.assert_not_called()
    assert json.loads(result.output)["verified"] is False


@pytest.mark.parametrize(
    "actions,expected",
    [
        (["delete"], "destroy"),
        (["delete", "create"], "replace"),
        (["create", "delete"], "replace"),
        (["update"], None),
        (["no-op"], None),
    ],
)
def test_plan_actions_independent_of_model(tmp_path, actions, expected):
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "resource_changes": [
                    {"address": "aws_db_instance.production", "change": {"actions": actions}}
                ],
            }
        )
    )
    with patch(
        "radea.core.llm.call",
        return_value={"summary": "No issues", "findings": [], "destructive_actions": []},
    ):
        run = CliRunner().invoke(main, ["iac-review", "--plan", str(path), "--output", "json"])
    assert run.exit_code == 0, run.output
    result = json.loads(run.output)
    assert result["deterministic"]["status"] == "complete"
    assert [a["action"] for a in result["destructive_actions"]] == ([expected] if expected else [])
    assert result["draft"] is True and result["verified"] is False


def test_destroy_survives_failed_model_and_long_tf(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "resource_changes": [
                    {"address": "aws_db_instance.production", "change": {"actions": ["delete"]}}
                ],
            }
        )
    )
    tf = tmp_path / "main.tf"
    tf.write_text("# Terraform configuration\n" * 4000)
    with patch("radea.core.llm.call", return_value={"error": "backend unavailable"}) as model:
        run = CliRunner().invoke(
            main, ["iac-review", "--file", str(tf), "--plan", str(plan), "--output", "json"]
        )
    assert run.exit_code == 1
    result = json.loads(run.output)
    assert result["destructive_actions"][0]["action"] == "destroy"
    assert "aws_db_instance.production" in model.call_args.kwargs["user"]


@pytest.mark.parametrize(
    "plan",
    [
        {},
        {"format_version": "1.2", "resource_changes": None},
        {
            "format_version": "1.2",
            "resource_changes": [{"address": "x", "change": {"actions": ["mystery"]}}],
        },
    ],
)
def test_invalid_plan_never_reported_safe(tmp_path, plan):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    with patch("radea.core.llm.call") as model:
        run = CliRunner().invoke(main, ["iac-review", "--plan", str(path), "--output", "json"])
    assert run.exit_code == 1
    assert json.loads(run.output)["plan_status"] == "invalid_or_unreadable"
    model.assert_not_called()


def test_valid_evidence_contract_and_metadata(tmp_path):
    path = tmp_path / "ci.log"
    path.write_text("ERROR module missing\n")
    response = {
        "category": "code_error",
        "hypotheses": [
            {
                "title": "Module missing",
                "description": "The import failed",
                "confidence": "high",
                "verify": "inspect requirements.txt",
                "evidence_ids": ["s1:L1"],
            }
        ],
        "verified": True,
        "unvalidated_extension": "discard this",
    }
    with patch("radea.core.llm.call", return_value=response):
        run = CliRunner().invoke(main, ["debug", "--log", str(path), "--output", "json"])
    assert run.exit_code == 0, run.output
    result = json.loads(run.output)
    assert result["verified"] is False
    assert result["evidence_verified"] is True
    assert result["evidence"]["s1:L1"] == "ERROR module missing"
    assert "unvalidated_extension" not in result
    rows = [
        json.loads(line)
        for line in (Path(os.environ["RADEA_AUDIT_DIR"]) / "audit.jsonl").read_text().splitlines()
    ]
    assert [r["status"] for r in rows] == ["started", "draft"]
    assert "ERROR module missing" not in json.dumps(rows)
    assert len(rows[0]["prompt_sha256"]) == 64
    assert (Path(os.environ["RADEA_AUDIT_DIR"]) / "audit.jsonl").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "response",
    [
        {"unrelated": 123},
        {"category": "unknown", "hypotheses": [{}]},
        {
            "category": "code_error",
            "hypotheses": [
                {
                    "title": "x",
                    "description": "x",
                    "verify": "x",
                    "confidence": "high",
                    "evidence_ids": ["s99:L1"],
                }
            ],
        },
    ],
)
def test_bad_model_output_is_rejected_without_renderer_crash(tmp_path, response):
    path = tmp_path / "ci.log"
    path.write_text("ERROR actual evidence")
    with patch("radea.core.llm.call", return_value=response):
        run = CliRunner().invoke(main, ["debug", "--log", str(path), "--output", "json"])
    assert run.exit_code == 1
    assert json.loads(run.output)["evidence_verified"] is False


def test_fabricated_quote_rejected():
    response = {
        "patterns": [],
        "timeline": [
            {
                "time": "01:23",
                "event": "Imaginary deploy",
                "source_line": "fabricated",
                "evidence_ids": ["s1:L1"],
            }
        ],
        "probable_cause": "Unknown",
        "postmortem_draft": "Draft",
    }
    with pytest.raises(ContractError, match="quote"):
        validate("triage", response, {"s1:L1": "ERROR actual event"})


@pytest.mark.parametrize("model", ["typo/private-model", "openai/", "kiro/", "openai/unsafe key"])
def test_invalid_provider_never_falls_back(model):
    with patch("radea.core.llm._call_openai") as cloud:
        assert "error" in llm.call(system="s", user="u", cfg=Config(model=model))
    cloud.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "https://remote.example",
        "http://10.0.0.2:11434",
        "http://u:p@localhost:11434",
        "http://localhost:11434/?token=x",
    ],
)
def test_remote_ollama_rejected_by_default(url):
    with pytest.raises(ValueError):
        llm.selection(Config(model="ollama/demo", ollama_base_url=url))


def test_explicit_remote_consent_and_local_boundary():
    cfg = Config(
        model="ollama/demo", ollama_base_url="https://remote.example", allow_remote_ollama=True
    )
    assert llm.selection(cfg) == ("ollama", "demo")
    cfg.local = True
    with pytest.raises(ValueError):
        llm.selection(cfg)


def test_provider_exception_does_not_leak_credentials():
    secret = "ghp_" + "a" * 30
    with patch("radea.core.llm._call_openai", side_effect=RuntimeError(secret)):
        result = llm.call(system="s", user="u", cfg=Config())
    assert secret not in str(result)


def test_audit_failure_prevents_inference(tmp_path, monkeypatch):
    path = tmp_path / "ci.log"
    path.write_text("ERROR failed")
    monkeypatch.setenv("RADEA_AUDIT_DIR", str(path))
    with patch("radea.core.llm.call") as model:
        run = CliRunner().invoke(main, ["debug", "--log", str(path), "--output", "json"])
    assert run.exit_code == 1
    model.assert_not_called()


def test_real_subprocess_adapter_isolates_credentials(tmp_path, monkeypatch):
    executable = tmp_path / "kiro-cli"
    executable.write_text(
        f"#!{sys.executable}\n"
        + """import json,os,sys
from pathlib import Path
profile=json.loads(Path('.kiro/agents/radea-analysis.json').read_text())
assert profile['tools']==[]
assert 'OPENAI_API_KEY' not in os.environ
assert 'GITHUB_TOKEN' not in os.environ
assert sys.stdin.read()=='sanitized payload'
print(json.dumps({'ok':True}))
"""
    )
    executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("OPENAI_API_KEY", "demo-key")
    monkeypatch.setenv("GITHUB_TOKEN", "demo-github")
    assert llm.call(system="s", user="sanitized payload", cfg=Config(model="kiro")) == {"ok": True}


def test_raw_input_switch_cannot_bypass_policy(tmp_path):
    path = tmp_path / "ci.log"
    path.write_text("password=demo")
    with patch("radea.core.llm.call") as model:
        run = CliRunner().invoke(
            main, ["debug", "--log", str(path), "--no-sanitize", "--output", "json"]
        )
    assert run.exit_code == 1
    model.assert_not_called()


def test_supplied_metrics_comparison_is_deterministic(tmp_path):
    from radea.incident_triage.metrics import compare

    path = tmp_path / "metrics.json"
    path.write_text(
        json.dumps(
            {
                "baseline": {"window": "7d", "values": {"latency": 100, "errors": 0}},
                "current": {"latency": 125, "errors": 2},
            }
        )
    )
    result = compare(str(path), "7d", 65536)
    assert result[0]["change_percent"] == 25
    assert result[1]["change_percent"] is None
    with pytest.raises(ValueError):
        compare(str(path), "24h", 65536)


@pytest.mark.parametrize(
    "actions,approved,expected",
    [
        (["update"], False, 0),
        (["delete"], False, 2),
        (["delete", "create"], False, 2),
        (["delete"], True, 0),
        (["mystery"], True, 1),
    ],
)
def test_allow_deny_policy_without_llm(tmp_path, actions, approved, expected):
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "resource_changes": [{"address": "db", "change": {"actions": actions}}],
            }
        )
    )
    args = ["policy-check", "--plan", str(path)] + (["--allow-destruction"] if approved else [])
    with patch("radea.core.llm.call") as model:
        run = CliRunner().invoke(main, args)
    assert run.exit_code == expected, run.output
    model.assert_not_called()


def test_local_iam_rule_cannot_be_suppressed_by_model(tmp_path):
    path = tmp_path / "main.tf"
    path.write_text('Action = ["*"]\nResource = "*"\n')
    with patch("radea.core.llm.call", return_value={"summary": "Draft", "findings": []}):
        run = CliRunner().invoke(main, ["iac-review", "--file", str(path), "--output", "json"])
    result = json.loads(run.output)
    assert run.exit_code == 0
    assert len(result["local_policy_findings"]) == 2
    assert all(f["origin"] == "local_literal_rule" for f in result["findings"])


def test_identifier_placeholders_are_stable_per_request(tmp_path):
    path = tmp_path / "ci.log"
    path.write_text("db.internal\ncache.internal\ndb.internal\n")
    sources = collect([str(path)], Config())
    assert sources.records["s1:L1"] == sources.records["s1:L3"]
    assert sources.records["s1:L1"] != sources.records["s1:L2"]
    assert "db.internal" not in sources.payload()


def test_redaction_alias_memory_is_bounded():
    aliases = {}
    for index in range(1100):
        sanitize(f"host{index}.internal", aliases=aliases)
    assert len(aliases) == 1024


def test_symlink_audit_target_is_rejected(tmp_path, monkeypatch):
    audit = tmp_path / "audit"
    audit.mkdir(exist_ok=True)
    target = tmp_path / "private"
    target.write_text("unchanged")
    (audit / "audit.jsonl").symlink_to(target)
    monkeypatch.setenv("RADEA_AUDIT_DIR", str(audit))
    path = tmp_path / "ci.log"
    path.write_text("ERROR failure")
    with patch("radea.core.llm.call") as model:
        run = CliRunner().invoke(main, ["debug", "--log", str(path), "--output", "json"])
    assert run.exit_code == 1
    model.assert_not_called()
    assert target.read_text() == "unchanged"


@pytest.mark.parametrize("value", ["two words", "special; braces} comma, colon:", ""])
def test_quoted_secret_assignment_does_not_leave_a_suffix(value):
    result = sanitize(json.dumps({"password": value}))
    assert json.loads(result.text)["password"] == "[REDACTED]"


def test_escaped_json_secret_value_is_fully_redacted():
    result = sanitize(json.dumps({"password": 'a "quoted" and apostrophe\' secret\\value'}))
    assert json.loads(result.text)["password"] == "[REDACTED]"
