"""Best-effort redaction at input and output boundaries; never a DLP guarantee."""

import re
from dataclasses import dataclass, field

REDACT = "[REDACTED]"
_PATTERNS = [
    (
        "pem",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"
        ),
    ),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA|AROA|AIDA)[A-Z0-9]{16}\b")),
    ("github_pat", re.compile(r"\b(?:ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_]{20,}")),
    (
        "provider_key",
        re.compile(r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{30,})"),
    ),
    (
        "auth_header",
        re.compile(
            r"(?i)(Authorization[\"']?\s*[:=]\s*[\"']?(?:Bearer|Basic|Token)\s+)([^\s\"',}]+)"
        ),
    ),
    ("url_password", re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:)([^\s@]+)(@)")),
    (
        "assignment",
        re.compile(
            r"(?i)((?<![\w])(?:aws_secret(?:_access)?_key|[\w.-]*(?:password|passwd|token|api[_-]?key|secret|credential)[\w.-]*|auth)[\"']?\s*[:=]\s*[\"']?)(?!\[REDACTED\])([^\s\"'`,;}\]]+)"
        ),
    ),
    (
        "signed_url",
        re.compile(
            r"(?i)([?&](?:X-Amz-(?:Signature|Credential|Security-Token)|sig|signature|access_token)=)([^&\s\"']+)"
        ),
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("internal_host", re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+(?:internal|local|corp|private)\b")),
    (
        "private_ip",
        re.compile(
            r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
        ),
    ),
]


@dataclass
class SanitizeResult:
    text: str
    redactions: int = 0
    types_found: list[str] = field(default_factory=list)


def sanitize(text: str, *, aliases: dict | None = None) -> SanitizeResult:
    aliases = {} if aliases is None else aliases
    count = 0
    found = []
    for name, pattern in _PATTERNS:

        def replace(match: re.Match, kind: str = name) -> str:
            nonlocal count
            count += 1
            if kind not in found:
                found.append(kind)
            if kind in {"email", "internal_host", "private_ip"}:
                label = {"email": "EMAIL", "internal_host": "HOST", "private_ip": "IP"}[kind]
                key = (kind, match[0])
                if key not in aliases and len(aliases) >= 1024:
                    return f"[{label}_OTHER]"
                if key not in aliases:
                    aliases[key] = f"[{label}_{1 + sum(k[0] == kind for k in aliases)}]"
                return aliases[key]
            if match.lastindex and match.lastindex >= 2:
                return match[1] + REDACT + (match[3] if match.lastindex >= 3 else "")
            return REDACT

        text = pattern.sub(replace, text)
    return SanitizeResult(text, count, found)


def clean(value):
    """Redact string values recursively without changing JSON structure or IDs."""
    if isinstance(value, str):
        return sanitize(value).text
    if isinstance(value, dict):
        return {
            sanitize(str(key)).text: (
                REDACT
                if re.fullmatch(
                    r"(?i)(?:password|passwd|token|api[_-]?key|secret|credential|private_key)",
                    str(key),
                )
                else clean(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value
