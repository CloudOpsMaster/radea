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
from dataclasses import dataclass, field
from pathlib import Path

RADEA_DIR = Path.home() / ".radea"


@dataclass
class Config:
    model: str = "openai/gpt-4o"
    kiro_timeout: int = 120
    local: bool = False
    sanitize: bool = True
    audit: bool = True
    max_log_chars: int = 32_000
    ollama_base_url: str = "http://localhost:11434"
    max_input_bytes: int = 8 * 1024 * 1024
    allow_remote_ollama: bool = False
    audit_dir: str = str(RADEA_DIR)
    openai_api_key: str = field(default="", repr=False)
    anthropic_api_key: str = field(default="", repr=False)
    google_api_key: str = field(default="", repr=False)

    def __post_init__(self):
        if not 2048 <= self.max_log_chars <= 128_000:
            raise ValueError("RADEA_MAX_LOG_CHARS must be between 2048 and 128000")
        if not 65536 <= self.max_input_bytes <= 32 * 1024 * 1024:
            raise ValueError("RADEA_MAX_INPUT_BYTES must be between 65536 and 33554432")
        if not 1 <= self.kiro_timeout <= 600:
            raise ValueError("RADEA_KIRO_TIMEOUT must be between 1 and 600")

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            max_input_bytes=int(os.getenv("RADEA_MAX_INPUT_BYTES", str(cls.max_input_bytes))),
            allow_remote_ollama=os.getenv("RADEA_ALLOW_REMOTE_OLLAMA", "").lower() == "true",
            audit_dir=os.getenv("RADEA_AUDIT_DIR", str(RADEA_DIR)),
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
