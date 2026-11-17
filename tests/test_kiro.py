"""Offline checks for Kiro's process boundary and provider selection."""

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from radea.core import llm
from radea.core.config import Config


@pytest.mark.parametrize("selection,model", [("kiro", ""), ("kiro/test-model", "test-model")])
def test_kiro_process_contract(selection, model):
    def run(command, **kwargs):
        profile = json.loads((Path(kwargs["cwd"]) / ".kiro/agents/radea-analysis.json").read_text())
        assert profile["tools"] == []
        assert profile["resources"] == []
        assert profile["includeMcpJson"] is False
        assert profile["prompt"] == "system"
        assert kwargs["input"] == "sanitized payload"
        assert kwargs["timeout"] == 120
        assert "sanitized payload" not in command
        assert "--trust-all-tools" not in command
        assert ("--model" in command) == bool(model)
        if model:
            assert command[-1] == model
        return subprocess.CompletedProcess(command, 0, '{"ok":true}', "")

    with patch("radea.core.llm.subprocess.run", side_effect=run):
        assert llm.call(system="system", user="sanitized payload", cfg=Config(model=selection)) == {
            "ok": True
        }


@pytest.mark.parametrize(
    "failure", [FileNotFoundError(), subprocess.TimeoutExpired("kiro-cli", 120)]
)
def test_kiro_startup_errors(failure):
    with patch("radea.core.llm.subprocess.run", side_effect=failure):
        assert "error" in llm.call(system="s", user="u", cfg=Config(model="kiro"))


def test_kiro_stderr_not_exposed():
    response = subprocess.CompletedProcess([], 1, "", "token=private-credential")
    with patch("radea.core.llm.subprocess.run", return_value=response):
        result = llm.call(system="s", user="u", cfg=Config(model="kiro"))
    assert "error" in result
    assert "private-credential" not in str(result)


def test_local_overrides_cloud_provider():
    with patch("radea.core.llm._call_ollama", return_value={"ok": True}) as local:
        assert llm.call(system="s", user="u", cfg=Config(local=True, model="kiro")) == {"ok": True}
    assert local.call_args.kwargs["model"] == "llama3.2"


@pytest.mark.parametrize("raw", ["[]", "null", '"text"', "123"])
def test_model_must_return_object(raw):
    with pytest.raises(ValueError, match="JSON object"):
        llm._parse(raw)


@pytest.mark.parametrize(
    "command,flag", [("debug", "--log"), ("triage", "--logs"), ("iac-review", "--file")]
)
@pytest.mark.parametrize("output", ["json", "text"])
def test_cli_provider_failure_exits_nonzero(tmp_path, command, flag, output):
    from click.testing import CliRunner

    from radea.cli import main

    source = tmp_path / "input.txt"
    source.write_text("build failed")
    with patch("radea.core.llm.call", return_value={"error": "backend unavailable"}):
        result = CliRunner().invoke(main, [command, flag, str(source), "--output", output])
    assert result.exit_code == 1
    assert "backend unavailable" in result.output
    if output == "json":
        assert json.loads(result.output)["error"] == "backend unavailable"


@pytest.mark.parametrize(
    "command,flag,extra",
    [
        ("triage", "--logs", "--metrics"),
        ("iac-review", "--file", "--context"),
    ],
)
def test_auxiliary_inputs_sanitized(tmp_path, command, flag, extra):
    from click.testing import CliRunner

    from radea.cli import main

    source = tmp_path / "input.txt"
    source.write_text("build failed")
    context = tmp_path / "context.txt"
    context.write_text(
        json.dumps(
            {
                "baseline": {"window": "7d", "values": {"errors": 1}},
                "current": {"errors": 2},
                "note": "token=supersecretvalue1234567890ab",
            }
        )
        if command == "triage"
        else "token=supersecretvalue1234567890ab"
    )
    response = (
        {"summary": "Review draft", "findings": []}
        if command == "iac-review"
        else {
            "patterns": [],
            "timeline": [],
            "probable_cause": "Unknown",
            "postmortem_draft": "Insufficient evidence",
        }
    )
    with patch("radea.core.llm.call", return_value=response) as model:
        result = CliRunner().invoke(main, [command, flag, str(source), extra, str(context)])
    assert result.exit_code == 0
    assert "supersecretvalue" not in model.call_args.kwargs["user"]
    assert "[REDACTED]" in model.call_args.kwargs["user"]
