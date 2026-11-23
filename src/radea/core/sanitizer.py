"""Best-effort redaction at input and output boundaries; never a DLP guarantee."""

import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

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
        "gitlab_token",
        re.compile(r"\bgl(?:pat|dt|ptt|rt|cbt|ft|imt|agent|soat|oas|ffct)-[A-Za-z0-9_.-]{16,}"),
    ),
    ("jwt", re.compile(r"\bey[A-Za-z0-9_-]{8,}\.ey[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    (
        "service_token",
        re.compile(
            r"\b(?:xox[abprs]-[A-Za-z0-9-]{10,}|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"
            r"|npm_[A-Za-z0-9]{30,}|pypi-AgEI[A-Za-z0-9_-]{20,}|ya29\.[A-Za-z0-9_-]{20,}"
            r"|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}|dckr_pat_[A-Za-z0-9_-]{16,}"
            r"|hvs\.[A-Za-z0-9_-]{20,})"
        ),
    ),
    (
        "netrc_password",
        re.compile(r"(?i)(\blogin\s+\S+\s+(?:account\s+\S+\s+)?password\s+)(?!\[REDACTED\])(\S+)"),
    ),
    (
        "netrc_password_line",
        re.compile(
            r"(?im)(^\s*password\s+)(?!\[REDACTED\]|(?:is|for|required|incorrect|invalid|expired"
            r"|missing|empty|must|should|cannot|can't|does|did|not|policy|hash|prompt|mismatch"
            r"|rejected|changed|reset|file)\b)(\S+)\s*$"
        ),
    ),
    (
        "auth_header",
        re.compile(
            r"(?i)(Authorization[\"']?\s*[:=]\s*[\"']?(?:Bearer|Basic|Token)\s+)([^\s\"',}]+)"
        ),
    ),
    ("url_password", re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:)([^\s@]+)(@)")),
    (
        "quoted_assignment",
        re.compile(
            r"""(?i)((?<![\w])(?:[\w.-]*(?:password|passwd|token|api[_-]?key|secret|credential|account[_-]?key|access[_-]?key|private[_-]?key|signing[_-]?key|client[_-]?key[_-]?data)[\w.-]*|auth)["']?\s*[:=]\s*")((?:\\.|[^"\\\r\n])*)(")"""
        ),
    ),
    (
        "single_quoted_assignment",
        re.compile(
            r"""(?i)((?<![\w])(?:[\w.-]*(?:password|passwd|token|api[_-]?key|secret|credential|account[_-]?key|access[_-]?key|private[_-]?key|signing[_-]?key|client[_-]?key[_-]?data)[\w.-]*|auth)["']?\s*[:=]\s*')((?:\\.|[^'\\\r\n])*)(')"""
        ),
    ),
    (
        "assignment",
        re.compile(
            r"(?i)((?<![\w])(?:aws_secret(?:_access)?_key|[\w.-]*(?:password|passwd|token|api[_-]?key|secret|credential|account[_-]?key|access[_-]?key|private[_-]?key|signing[_-]?key|client[_-]?key[_-]?data)[\w.-]*|auth)[\"']?\s*[:=]\s*[\"']?)(?!\[REDACTED\])([^\s\"'`,;}\]]+)"
        ),
    ),
    (
        "signed_url",
        re.compile(
            r"(?i)([?&](?:X-Amz-(?:Signature|Credential|Security-Token)|sig|signature|access_token)=)([^&\s\"']+)"
        ),
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        "internal_host",
        re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+(?:internal|local|corp|private)(?![\w-])"),
    ),
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


def _normalize(text: str) -> str:
    """Drop invisible format characters and fold full-width forms before matching.

    Zero-width characters inside a key name (``pass\u200bword=...``) would otherwise hide a
    secret from every pattern. ASCII-only input is returned unchanged.
    """
    if text.isascii():
        return text
    visible = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return unicodedata.normalize("NFKC", visible)


@lru_cache(maxsize=8)
def _extra_hosts(spec: str) -> re.Pattern | None:
    names = [item.strip().lstrip(".").lower() for item in spec.split(",") if item.strip()]
    names = [name for name in names if re.fullmatch(r"[a-z0-9.-]{3,253}", name)][:32]
    if not names:
        return None
    alternatives = "|".join(re.escape(name) for name in names)
    return re.compile(rf"(?i)\b(?:[a-z0-9-]+\.)*(?:{alternatives})\b")


def sanitize(text: str, *, aliases: dict | None = None) -> SanitizeResult:
    aliases = {} if aliases is None else aliases
    count = 0
    found = []
    text = _normalize(text)
    patterns = list(_PATTERNS)
    extra = _extra_hosts(os.getenv("RADEA_INTERNAL_DOMAINS", ""))
    if extra is not None:
        patterns.append(("internal_host", extra))
    for name, pattern in patterns:

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


_SENSITIVE_KEY = re.compile(
    r"(?i)password|passwd|token|api[_-]?key|secret|credential|private[_-]?key"
    r"|account[_-]?key|access[_-]?key|signing[_-]?key|client[_-]?key[_-]?data"
)


def clean(value):
    """Redact string values recursively without changing JSON structure or IDs."""
    if isinstance(value, str):
        return sanitize(value).text
    if isinstance(value, dict):
        return {
            sanitize(str(key)).text: (
                REDACT
                if re.fullmatch(
                    r"(?i)(?:password|passwd|token|api[_-]?key|secret|credential|account[_-]?key|access[_-]?key|private[_-]?key|signing[_-]?key|client[_-]?key[_-]?data|private_key)",
                    str(key),
                )
                else REDACT
                if isinstance(item, str) and _SENSITIVE_KEY.search(str(key))
                else clean(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value
