"""Public facade contracts: dependency injection, silence and configuration isolation."""

import dataclasses
import json

import pytest

from radea.api import AnalysisRequest, AnalysisService, Config, analyze


def test_python_api_returns_data_without_printing(tmp_path, capsys):
    path = tmp_path / "ci.log"
    path.write_text("ERROR missing module\n")
    seen = []

    def model(*, system, user, cfg):
        seen.append(json.loads(user))
        return {
            "category": "code_error",
            "hypotheses": [
                {
                    "title": "Import error",
                    "description": "The module is missing",
                    "verify": "inspect requirements.txt",
                    "confidence": "low",
                    "evidence_ids": ["s1:L1"],
                }
            ],
        }

    result = analyze(
        AnalysisRequest(command="debug", paths=(str(path),)),
        config=Config(audit=False),
        model=model,
    )
    assert result["evidence_verified"] is True
    assert result["draft"] is True
    assert seen[0]["evidence"]["s1:L1"] == "ERROR missing module"
    assert capsys.readouterr().out == ""


def test_service_does_not_mutate_shared_configuration(tmp_path):
    path = tmp_path / "ci.log"
    path.write_text("ERROR failed")
    config = Config(audit=False)
    service = AnalysisService(config, lambda **kwargs: {"category": "unknown", "hypotheses": []})
    result = service.analyze(AnalysisRequest(command="debug", paths=(str(path),), local=True))
    assert config.local is False
    assert result["provenance"]["provider"] == "ollama"


def test_request_is_immutable_and_rejects_invalid_combinations():
    request = AnalysisRequest(command="debug", paths=("ci.log",))
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.local = True
    with pytest.raises(ValueError):
        AnalysisRequest(command="debug", plan_file="plan.json")
    with pytest.raises(ValueError):
        AnalysisRequest(command="triage")


def test_injected_model_cannot_bypass_result_validation(tmp_path):
    path = tmp_path / "ci.log"
    path.write_text("ERROR actual fact")
    result = analyze(
        AnalysisRequest(command="debug", paths=(str(path),)),
        config=Config(audit=False),
        model=lambda **kwargs: {"verified": True},
    )
    assert result["error"] and result["verified"] is False
