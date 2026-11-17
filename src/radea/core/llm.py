"""LLM client — routes to the correct provider based on model name.

Supported providers (auto-detected from RADEA_MODEL):
  openai/...    — OpenAI API       requires OPENAI_API_KEY
  anthropic/... — Anthropic API    requires ANTHROPIC_API_KEY
  google/...    — Google Gemini    requires GOOGLE_API_KEY
  ollama/...    — Ollama endpoint  no key; remote access requires explicit consent
  ollama        — local Ollama     shorthand, uses default model

Examples:
  RADEA_MODEL=openai/gpt-4o
  RADEA_MODEL=openai/gpt-4o-mini
  RADEA_MODEL=anthropic/claude-3-5-sonnet-20241022
  RADEA_MODEL=google/gemini-1.5-flash
  RADEA_MODEL=ollama/llama3.2
  RADEA_MODEL=ollama/mistral
  RADEA_MODEL=ollama/qwen2.5-coder
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from radea.core.config import Config
from radea.core.provider_errors import details


def call(*, system: str, user: str, cfg: Config) -> dict:
    """Route to the correct provider and return a parsed JSON dict."""
    try:
        provider, model = selection(cfg)
        if provider == "offline":
            raise ValueError("Offline analysis must use AnalysisService")
        if provider == "kiro":
            return _call_kiro(system=system, user=user, model=model, cfg=cfg)
        if provider == "ollama":
            return _call_ollama(system=system, user=user, model=model, cfg=cfg)
        if provider == "anthropic":
            return _call_anthropic(system=system, user=user, model=model, cfg=cfg)
        if provider == "google":
            return _call_google(system=system, user=user, model=model, cfg=cfg)
        return _call_openai(system=system, user=user, model=model, cfg=cfg)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"Provider request failed ({type(exc).__name__}); "
            "check credentials, endpoint and model",
            **details(exc),
        }


# ── Providers ─────────────────────────────────────────────────────────────────


def _call_openai(*, system: str, user: str, model: str, cfg: Config) -> dict:
    import openai

    if not cfg.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required")
    client = openai.OpenAI(
        api_key=cfg.openai_api_key, base_url="https://api.openai.com/v1", timeout=60, max_retries=0
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        max_tokens=4096,
    )
    return _parse(resp.choices[0].message.content)


def _call_anthropic(*, system: str, user: str, model: str, cfg: Config) -> dict:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic") from None

    if not cfg.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required")
    client = anthropic.Anthropic(
        api_key=cfg.anthropic_api_key,
        base_url="https://api.anthropic.com",
        timeout=60,
        max_retries=0,
    )
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _parse(resp.content[0].text)


def _call_google(*, system: str, user: str, model: str, cfg: Config) -> dict:
    from google import genai

    if not cfg.google_api_key:
        raise ValueError("GOOGLE_API_KEY is required")
    with genai.Client(
        api_key=cfg.google_api_key,
        vertexai=False,
        http_options={"timeout": 60000, "base_url": "https://generativelanguage.googleapis.com"},
    ) as client:
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config={
                "system_instruction": system,
                "max_output_tokens": 4096,
                "response_mime_type": "application/json",
                "temperature": 0,
            },
        )
    return _parse(resp.text)


def _call_ollama(*, system: str, user: str, model: str, cfg: Config) -> dict:
    """Ollama uses the OpenAI-compatible /v1 endpoint — no extra package needed."""
    import openai

    _ollama_endpoint(cfg)
    client = openai.OpenAI(
        api_key="ollama",
        base_url=f"{cfg.ollama_base_url.rstrip('/')}/v1",
        timeout=60,
        max_retries=0,
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
        max_tokens=4096,
    )
    return _parse(resp.choices[0].message.content)


def _call_kiro(*, system: str, user: str, model: str, cfg: Config) -> dict:
    """Run an authenticated Kiro CLI with an isolated, tool-free agent."""
    with tempfile.TemporaryDirectory(prefix="radea-kiro-") as directory:
        agents = Path(directory) / ".kiro" / "agents"
        agents.mkdir(parents=True)
        (agents / "radea-analysis.json").write_text(
            json.dumps(
                {
                    "name": "radea-analysis",
                    "description": "Return analysis JSON without tools",
                    "prompt": system,
                    "tools": [],
                    "resources": [],
                    "includeMcpJson": False,
                }
            )
        )
        command = ["kiro-cli", "chat", "--no-interactive", "--agent", "radea-analysis"]
        if model:
            command.extend(["--model", model])
        try:
            response = subprocess.run(
                command,
                input=user,
                text=True,
                capture_output=True,
                cwd=directory,
                timeout=cfg.kiro_timeout,
                check=False,
                env={
                    key: value
                    for key, value in os.environ.items()
                    if key
                    in {
                        "PATH",
                        "HOME",
                        "USER",
                        "TMPDIR",
                        "LANG",
                        "LC_ALL",
                        "XDG_CONFIG_HOME",
                        "XDG_DATA_HOME",
                        "XDG_STATE_HOME",
                        "XDG_CACHE_HOME",
                        "KIRO_API_KEY",
                        "AWS_PROFILE",
                        "AWS_REGION",
                        "AWS_DEFAULT_REGION",
                        "AWS_CONFIG_FILE",
                        "AWS_SHARED_CREDENTIALS_FILE",
                    }
                },
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Install kiro-cli and authenticate before selecting RADEA_MODEL=kiro"
            ) from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "Kiro CLI timed out; check authentication and RADEA_KIRO_TIMEOUT"
            ) from None
        if response.returncode:
            # CLI stderr can echo the prompt or credentials. Do not expose it.
            raise RuntimeError(
                f"Kiro CLI failed (exit {response.returncode}); check Kiro authentication"
            )
        return _parse(response.stdout)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _ollama_endpoint(cfg):
    parsed = urlsplit(cfg.ollama_base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Invalid Ollama endpoint")
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if not loopback and (cfg.local or not cfg.allow_remote_ollama or parsed.scheme != "https"):
        raise ValueError(
            "Remote Ollama requires HTTPS and RADEA_ALLOW_REMOTE_OLLAMA=true; "
            "--local requires loopback"
        )


def selection(cfg):
    provider, model = _parse_model(cfg.model)
    if cfg.local:
        provider, model = "ollama", model if provider == "ollama" else "llama3.2"
    if provider == "ollama":
        _ollama_endpoint(cfg)
    return provider, model


def _parse_model(model_str: str) -> tuple[str, str]:
    """Split 'provider/model-name' into (provider, model).

    'ollama' alone → ('ollama', 'llama3.2')
    'openai/gpt-4o' → ('openai', 'gpt-4o')
    'gpt-4o'        → ('openai', 'gpt-4o')   # bare name defaults to openai
    """
    if not isinstance(model_str, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", model_str):
        raise ValueError("Invalid model selection")
    if model_str in {"offline", "offline-linear", "offline-neural"}:
        return "offline", model_str
    if "/" not in model_str:
        if model_str == "kiro":
            return "kiro", ""
        if model_str == "ollama":
            return "ollama", "llama3.2"
        return "openai", model_str

    provider, _, name = model_str.partition("/")
    provider = provider.lower()
    if provider not in ("openai", "anthropic", "google", "ollama", "kiro"):
        raise ValueError("Unknown provider; choose openai, anthropic, google, ollama or kiro")
    if not name:
        raise ValueError("Model name cannot be empty")
    return provider, name


def _parse(raw: str) -> dict:
    """Parse JSON from model response, stripping markdown fences if present."""
    if not isinstance(raw, str) or len(raw) > 128_000:
        raise ValueError("Model output exceeds size limit or is not text")
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Model response must be a JSON object")
    return result
