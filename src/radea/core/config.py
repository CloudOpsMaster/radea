"""Runtime configuration. Priority: env vars > defaults.

Model examples:
  RADEA_MODEL=openai/gpt-4o            (default)
  RADEA_MODEL=openai/gpt-4o-mini
  RADEA_MODEL=anthropic/claude-3-5-sonnet-20241022
  RADEA_MODEL=google/gemini-1.5-flash
  RADEA_MODEL=ollama/llama3.2
  RADEA_MODEL=ollama/mistral
  RADEA_MODEL=ollama/qwen2.5-coder
  RADEA_MODEL=ollama                   (shorthand, uses llama3.2)
"""

import os
from dataclasses import dataclass
from pathlib import Path

RADEA_DIR = Path.home() / ".radea"
AUDIT_LOG = RADEA_DIR / "audit.log"


@dataclass
class Config:
    model: str = "openai/gpt-4o"
    kiro_timeout: int = 120
    local: bool = False
    sanitize: bool = True
    audit: bool = True
    max_log_chars: int = 32_000
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            kiro_timeout=int(os.getenv("RADEA_KIRO_TIMEOUT", "120")),
            model=os.getenv("RADEA_MODEL", cls.model),
            local=os.getenv("RADEA_LOCAL", "").lower() in ("1", "true"),
            sanitize=os.getenv("RADEA_SANITIZE", "true").lower() not in ("0", "false"),
            audit=os.getenv("RADEA_AUDIT", "true").lower() not in ("0", "false"),
            max_log_chars=int(os.getenv("RADEA_MAX_LOG_CHARS", str(cls.max_log_chars))),
            ollama_base_url=os.getenv("RADEA_OLLAMA_URL", cls.ollama_base_url),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        )
