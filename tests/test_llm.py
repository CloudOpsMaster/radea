"""Tests for core.llm — provider routing and model name parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from radea.core.config import Config
from radea.core.llm import _parse, _parse_model

# ── Model name parsing ────────────────────────────────────────────────────────


class TestParseModel:
    def test_openai_explicit(self):
        assert _parse_model("openai/gpt-4o") == ("openai", "gpt-4o")

    def test_openai_mini(self):
        assert _parse_model("openai/gpt-4o-mini") == ("openai", "gpt-4o-mini")

    def test_anthropic(self):
        assert _parse_model("anthropic/claude-3-5-sonnet-20241022") == (
            "anthropic",
            "claude-3-5-sonnet-20241022",
        )

    def test_google(self):
        assert _parse_model("google/gemini-1.5-flash") == ("google", "gemini-1.5-flash")

    def test_ollama_with_model(self):
        assert _parse_model("ollama/llama3.2") == ("ollama", "llama3.2")

    def test_ollama_mistral(self):
        assert _parse_model("ollama/mistral") == ("ollama", "mistral")

    def test_ollama_codellama(self):
        assert _parse_model("ollama/codellama") == ("ollama", "codellama")

    def test_ollama_bare(self):
        assert _parse_model("ollama") == ("ollama", "llama3.2")

    def test_bare_model_name_defaults_to_openai(self):
        provider, model = _parse_model("gpt-4o")
        assert provider == "openai"
        assert model == "gpt-4o"


# ── JSON parsing ──────────────────────────────────────────────────────────────


class TestParse:
    def test_plain_json(self):
        raw = '{"category": "code_error", "hypotheses": []}'
        assert _parse(raw) == {"category": "code_error", "hypotheses": []}

    def test_strips_markdown_fences(self):
        raw = '```json\n{"key": "value"}\n```'
        assert _parse(raw) == {"key": "value"}

    def test_strips_bare_fences(self):
        raw = '```\n{"key": "value"}\n```'
        assert _parse(raw) == {"key": "value"}

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse("not json at all")


# ── Provider routing ──────────────────────────────────────────────────────────


class TestProviderRouting:
    """Each provider must be called when its prefix is in the model name."""

    def _fake_response(self, text: str) -> MagicMock:
        resp = MagicMock()
        resp.choices[0].message.content = text
        return resp

    def test_routes_to_openai(self):
        cfg = Config(model="openai/gpt-4o", openai_api_key="sk-test")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._fake_response('{"ok": true}')

        import openai as _oa

        with patch.object(_oa, "OpenAI", return_value=mock_client):
            from radea.core import llm

            result = llm._call_openai(system="s", user="u", model="gpt-4o", cfg=cfg)

        assert result == {"ok": True}

    def test_routes_to_ollama(self):
        cfg = Config(model="ollama/llama3.2", ollama_base_url="http://localhost:11434")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._fake_response('{"ok": true}')

        import openai as _oa

        with patch.object(_oa, "OpenAI", return_value=mock_client) as mock_oa:
            from radea.core import llm

            result = llm._call_ollama(system="s", user="u", model="llama3.2", cfg=cfg)

        assert result == {"ok": True}
        assert mock_oa.call_args.kwargs.get("api_key") == "ollama"
        assert "localhost:11434" in mock_oa.call_args.kwargs.get("base_url", "")

    def test_error_returned_not_raised(self):
        """Exceptions from any provider must be returned as {"error": ...}."""
        cfg = Config(model="openai/gpt-4o", openai_api_key="")

        with patch("radea.core.llm._call_openai", side_effect=Exception("bad key")):
            from radea.core import llm

            result = llm.call(system="s", user="u", cfg=cfg)

        assert "error" in result
        assert "bad key" in result["error"]

    def test_ollama_no_api_key_needed(self):
        """Ollama must never require an API key env var."""
        cfg = Config(model="ollama/llama3.2", openai_api_key="")
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._fake_response('{"ok": true}')

        import openai as _oa

        with patch.object(_oa, "OpenAI", return_value=mock_client) as mock_oa:
            from radea.core import llm

            llm._call_ollama(system="s", user="u", model="llama3.2", cfg=cfg)

        # api_key must be the literal string "ollama", not a real key
        assert mock_oa.call_args.kwargs.get("api_key") == "ollama"
