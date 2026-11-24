import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from click.testing import CliRunner

from radea.cli import main

CRD = Path(__file__).resolve().parents[1] / "examples" / "k8s-operator" / "crd.yaml"


@pytest.mark.parametrize("status", [0, 1])
def test_crd_validate_uses_explicit_server_dry_run(monkeypatch, tmp_path, status):
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.touch()

    def kubectl(command, *, input, stderr, **kwargs):
        assert command[:5] == ["kubectl", "--kubeconfig", str(kubeconfig), "--context", "test"]
        assert command[6:] == [
            "apply", "--server-side", "--dry-run=server", "--validate=strict",
            "--field-manager=radea-crd-validation", "-f", "-",
        ]
        assert input == CRD.read_bytes()
        if status:
            stderr.write(b"openAPIV3Schema: unsupported type\n")
        return CompletedProcess(command, status)

    monkeypatch.setattr("radea.crd_validate.subprocess.run", kubectl)
    result = CliRunner().invoke(main, [
        "crd-validate", str(CRD), "--kubeconfig", str(kubeconfig), "--context", "test",
    ])
    assert result.exit_code == (2 if status else 0), result.output
    report = json.loads(result.output)
    assert report["accepted"] is (status == 0)
    assert report["name"] == "messages.lab.radea.dev"
    assert ("unsupported type" in report["diagnostic"]) is (status != 0)


@pytest.mark.parametrize("manifest", [
    "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: other}\n",
    CRD.read_text() + "\n---\nkind: ConfigMap\n",
    CRD.read_text() + "\nkind: Secret\n",
])
def test_crd_validate_rejects_other_and_ambiguous_objects_locally(monkeypatch, tmp_path, manifest):
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.touch()

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid local input reached kubectl")

    monkeypatch.setattr("radea.crd_validate.subprocess.run", unexpected)
    result = CliRunner().invoke(main, [
        "crd-validate", "-", "--kubeconfig", str(kubeconfig), "--context", "test",
    ], input=manifest)
    assert result.exit_code == 1, result.output
