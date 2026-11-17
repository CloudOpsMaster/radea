"""Offline behavior through the public API, with outbound calls forbidden."""

import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from radea.api import AnalysisRequest, Config, analyze
from radea.core.diagnostics import readiness
from radea.core.tiny import predict


@pytest.mark.parametrize("variant", ["offline", "offline-linear", "offline-neural"])
@pytest.mark.parametrize("command", ["debug", "triage", "iac-review"])
def test_offline_has_no_network_or_llm(tmp_path, variant, command):
    log = tmp_path / "input.log"
    log.write_text("2026-11-17T10:00:00Z ModuleNotFoundError: demo\ntoken=private-value\n")
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")),
        patch("radea.core.llm.call", side_effect=AssertionError("LLM forbidden")),
    ):
        result = analyze(
            AnalysisRequest(command=command, paths=(str(log),)),
            config=Config(model=variant, audit=False),
        )
    assert "error" not in result
    assert result["analysis_origin"] == "deterministic_rules"
    assert result["evidence_verified"] and not result["verified"]
    assert "private-value" not in json.dumps(result)
    if variant != "offline" and command == "debug":
        assert result["classifier_hint"]["experimental"]
        assert result["category"] == "dependency_drift"


def test_default_ignores_available_cloud_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "private-value")
    log = tmp_path / "input.log"
    log.write_text("No familiar signals here\n")
    with patch("radea.core.llm.call") as provider:
        result = analyze(AnalysisRequest(command="debug", paths=(str(log),)))
    provider.assert_not_called()
    assert result["category"] == "unknown" and result["hypotheses"] == []
    assert Config.from_env().model == "offline"
    assert readiness(Config())["configured"]


def test_mixed_signals_do_not_claim_single_cause(tmp_path):
    log = tmp_path / "input.log"
    log.write_text("ModuleNotFoundError: demo\nPermissionError: denied\n")
    result = analyze(
        AnalysisRequest(command="debug", paths=(str(log),)), config=Config(audit=False)
    )
    assert result["category"] == "unknown"
    assert len(result["hypotheses"]) == 2


def test_triage_counts_retained_lines_and_preserves_evidence(tmp_path):
    log = tmp_path / "input.log"
    log.write_text("2026-11-17T10:00:00Z TimeoutError: slow\n" * 3)
    result = analyze(
        AnalysisRequest(command="triage", paths=(str(log),)), config=Config(audit=False)
    )
    pattern = result["patterns"][0]
    assert pattern["count"] == 3 and pattern["count_is_estimate"] is False
    assert pattern["count_scope"] == "retained_evidence_lines"
    assert len(result["timeline"]) == 3
    assert result["cause_status"] == "not_established"
    for entry in result["timeline"]:
        assert entry["source_line"] == result["evidence"][entry["evidence_ids"][0]]


def test_clipped_triage_does_not_count_omitted_lines(tmp_path):
    log = tmp_path / "input.log"
    log.write_text("TimeoutError: slow\n" * 5000)
    result = analyze(
        AnalysisRequest(command="triage", paths=(str(log),)),
        config=Config(audit=False, max_log_chars=2048),
    )
    assert result["provenance"]["incomplete"]
    assert result["patterns"][0]["count"] == len(result["evidence"]) < 5000


def test_offline_plan_never_loses_policy_facts():
    result = analyze(
        AnalysisRequest(command="iac-review", plan_file="examples/evaluation/delete-plan.json"),
        config=Config(audit=False),
    )
    assert "error" not in result
    assert result["destructive_actions"]
    assert any(f["severity"] == "high" for f in result["findings"])


def test_corpus_splits_by_family_and_artifacts_match():
    raw = Path("examples/offline/corpus.json").read_bytes()
    corpus = json.loads(raw)["cases"]
    partitions = {}
    for row in corpus:
        partitions.setdefault(row["family"], set()).add(row["split"])
        assert row["origin"] == "reproduced_python_process" and row["reproducer"]
    assert all(len(splits) == 1 for splits in partitions.values())
    for variant in ("offline-linear", "offline-neural"):
        artifact = json.loads(Path(f"src/radea/data/{variant}.json").read_text())
        assert artifact["corpus_sha256"] == hashlib.sha256(raw).hexdigest()
        hint = predict("ModuleNotFoundError: unavailable", variant)
        assert hint["calibrated_probability"] is False
        assert len(hint["artifact_sha256"]) == 64


def test_offline_draft_comment_does_not_claim_ai_output(tmp_path, capsys):
    from radea.notify.comment import post_comment

    log = tmp_path / "input.log"
    log.write_text("ModuleNotFoundError: demo\n")
    result = analyze(
        AnalysisRequest(command="debug", paths=(str(log),)), config=Config(audit=False)
    )
    output = tmp_path / "result.json"
    output.write_text(json.dumps(result))
    with patch.dict("os.environ", {}, clear=True):
        post_comment(str(output))
    assert "OFFLINE DRAFT" in capsys.readouterr().out


def test_empty_classifier_input_abstains():
    for variant in ("offline-linear", "offline-neural"):
        assert predict("", variant)["category"] == "unknown"
