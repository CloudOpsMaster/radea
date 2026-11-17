"""Strip secrets from text before any external call."""

import re
from dataclasses import dataclass, field

REDACT = "[REDACTED]"

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_key", re.compile(r"(?<![A-Z0-9])(AKIA|ASIA|AROA|AIDA)[A-Z0-9]{16}(?![A-Z0-9])")),
    (
        "aws_secret",
        re.compile(r"(?i)(aws_secret(?:_access)?_key\s*[=:]\s*['\"]?)([A-Za-z0-9/+=]{40})(['\"]?)"),
    ),
    (
        "token",
        re.compile(
            r"(?i)((?:token|api[_-]?key|secret|password|passwd|auth)\s*[=:]\s*['\"]?)([A-Za-z0-9\-_.~+/]{16,})(['\"]?)"
        ),
    ),
    (
        "auth_header",
        re.compile(r"(?i)(Authorization:\s*(?:Bearer|Basic|Token)\s+)([A-Za-z0-9\-_.~+/=]{16,})"),
    ),
    (
        "pem",
        re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----"),
    ),
    ("github_pat", re.compile(r"(ghp_|gho_|ghs_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("url_password", re.compile(r"(https?://[^:@\s]+:)([^@\s]+)(@)")),
]


@dataclass
class SanitizeResult:
    text: str
    redactions: int = 0
    types_found: list[str] = field(default_factory=list)


def sanitize(text: str) -> SanitizeResult:
    """Return *text* with secrets replaced by [REDACTED]."""
    count = 0
    types: list[str] = []

    for name, pattern in _PATTERNS:

        def _sub(m: re.Match[str], _n: str = name) -> str:
            nonlocal count
            count += 1
            if _n not in types:
                types.append(_n)
            # Keep prefix/suffix groups, redact only the secret value (group 2)
            if m.lastindex and m.lastindex >= 2:
                prefix = m.group(1)
                suffix = m.group(m.lastindex) if m.lastindex >= 3 else ""
                return f"{prefix}{REDACT}{suffix}"
            return REDACT

        text = pattern.sub(_sub, text)

    return SanitizeResult(text=text, redactions=count, types_found=types)
