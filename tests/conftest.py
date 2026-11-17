"""Isolate metadata audit writes from developer home and production credentials."""

import pytest


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setenv("RADEA_AUDIT_DIR", str(tmp_path / "audit"))
    for key in (
        "RADEA_LOCAL",
        "RADEA_SANITIZE",
        "RADEA_MODEL",
        "RADEA_MAX_LOG_CHARS",
        "RADEA_MAX_INPUT_BYTES",
        "RADEA_AUDIT",
        "RADEA_KIRO_TIMEOUT",
        "RADEA_ALLOW_REMOTE_OLLAMA",
        "RADEA_OLLAMA_URL",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def cloud_model(monkeypatch):
    """Provider contract tests opt in explicitly; application default stays offline."""
    monkeypatch.setenv("RADEA_MODEL", "openai/gpt-4o-mini")
