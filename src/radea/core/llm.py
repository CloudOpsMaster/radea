"""LLM client — routes to the correct provider based on model name.

Supported providers (auto-detected from RADEA_MODEL):
  openai/...    — OpenAI API       requires OPENAI_API_KEY
  anthropic/... — Anthropic API    requires ANTHROPIC_API_KEY
  google/...    — Google Gemini    requires GOOGLE_API_KEY
  ollama/...    — local Ollama     no key, data never leaves the machine
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
import subprocess
import tempfile
from pathlib import Path

from radea.core.config import Config


def call(*, system: str, user: str, cfg: Config) -> dict:
    """Route to the correct provider and return a parsed JSON dict."""
    provider, model = _parse_model(cfg.model)
    if cfg.local:
        provider, model = "ollama", model if provider == "ollama" else "llama3.2"

    try:
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
        return {"error": str(exc)}


# ── Providers ─────────────────────────────────────────────────────────────────


def _call_openai(*, system: str, user: str, model: str, cfg: Config) -> dict:
    import openai

    client = openai.OpenAI(api_key=cfg.openai_api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
    )
    return _parse(resp.choices[0].message.content)


def _call_anthropic(*, system: str, user: str, model: str, cfg: Config) -> dict:
    try:
        import anthropic
    except ImportError:
        raise ImportError("Run: pip install anthropic") from None

    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _parse(resp.content[0].text)


def _call_google(*, system: str, user: str, model: str, cfg: Config) -> dict:
    try:
        import google.generativeai as genai
    except ImportError:
        raise ImportError("Run: pip install google-generativeai") from None

    genai.configure(api_key=cfg.google_api_key)
    client = genai.GenerativeModel(
        model_name=model,
        system_instruction=system,
    )
    resp = client.generate_content(user)
    return _parse(resp.text)


def _call_ollama(*, system: str, user: str, model: str, cfg: Config) -> dict:
    """Ollama uses the OpenAI-compatible /v1 endpoint — no extra package needed."""
    import openai

    client = openai.OpenAI(
        api_key="ollama",
        base_url=f"{cfg.ollama_base_url}/v1",
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0,
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


def _parse_model(model_str: str) -> tuple[str, str]:
    """Split 'provider/model-name' into (provider, model).

    'ollama' alone → ('ollama', 'llama3.2')
    'openai/gpt-4o' → ('openai', 'gpt-4o')
    'gpt-4o'        → ('openai', 'gpt-4o')   # bare name defaults to openai
    """
    if "/" not in model_str:
        if model_str == "kiro":
            return "kiro", ""
        if model_str == "ollama":
            return "ollama", "llama3.2"
        return "openai", model_str

    provider, _, name = model_str.partition("/")
    provider = provider.lower()
    if provider not in ("openai", "anthropic", "google", "ollama", "kiro"):
        # Unknown prefix — treat the whole string as an openai model name
        return "openai", model_str
    return provider, name


def _parse(raw: str) -> dict:
    """Parse JSON from model response, stripping markdown fences if present."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Model response must be a JSON object")
    return result
