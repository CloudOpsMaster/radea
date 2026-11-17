"""Credential-safe readiness checks; live inference is always an explicit opt-in."""

import importlib.util
import shutil

from radea.core.config import Config
from radea.core.llm import selection


def readiness(config: Config) -> dict:
    provider, model = selection(config)
    modules = {
        "openai": "openai",
        "ollama": "openai",
        "anthropic": "anthropic",
        "google": "google.genai",
    }
    if provider == "kiro":
        installed = shutil.which("kiro-cli") is not None
        credential_present = None  # CLI-managed sessions cannot be inferred from an env key.
    else:
        try:
            installed = importlib.util.find_spec(modules[provider]) is not None
        except (ImportError, ValueError):
            installed = False
        credential_present = {
            "openai": bool(config.openai_api_key),
            "anthropic": bool(config.anthropic_api_key),
            "google": bool(config.google_api_key),
            "ollama": None,
        }[provider]
    ready = installed and credential_present is not False
    return {
        "provider": provider,
        "model": model,
        "client_installed": installed,
        "credential_present": credential_present,
        "configured": ready,
        "inference_tested": False,
        "authentication_verified": False,
        "next_step": "Run an explicit analysis smoke test"
        if ready
        else "Install the selected client and configure its authentication",
    }
