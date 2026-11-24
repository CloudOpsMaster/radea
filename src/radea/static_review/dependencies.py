"""Compare proposed dependency artifacts to an explicit approved inventory."""

import json
import re
from urllib.parse import urlsplit

from radea.core.sanitizer import clean
from radea.static_review.files import collect

DIGEST = re.compile(r"[a-f0-9]{64}\Z")
PURL = re.compile(r"pkg:[a-z][a-z0-9.+-]*/[^?#@\s]+@[^?#@\s]+(?:[?#]\S+)?\Z")


def _inventory(path: str, limit: int) -> tuple[dict[str, tuple[str, str]], dict]:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one dependency inventory file")
    source = sources[0]
    try:
        document = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid dependency inventory JSON") from None
    rows = document.get("dependencies") if isinstance(document, dict) else None
    if not isinstance(rows, list) or len(rows) > 10_000:
        raise ValueError("Expected a dependencies list of up to 10000 records")
    inventory = {}
    for position, row in enumerate(rows, 1):
        if (
            not isinstance(row, dict)
            or set(row) != {"purl", "registry", "sha256"}
            or not all(isinstance(value, str) and len(value) <= 512 for value in row.values())
        ):
            raise ValueError(f"Invalid dependency record at position {position}")
        purl, registry, digest = row["purl"], row["registry"], row["sha256"]
        if (
            not PURL.fullmatch(purl) or purl in inventory or not DIGEST.fullmatch(digest)
        ):
            raise ValueError(f"Invalid, duplicate or unpinned package at position {position}")
        try:
            parsed = urlsplit(registry)
            port = parsed.port
        except ValueError:
            raise ValueError(f"Invalid registry at position {position}") from None
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or any(char.isspace() or ord(char) < 32 for char in registry)
            or any(char in registry for char in "?#\\")
        ):
            raise ValueError(f"Expected a credential-free HTTPS registry at position {position}")
        host = parsed.hostname
        if ":" in host:
            host = f"[{host}]"
        authority = host if port in (None, 443) else f"{host}:{port}"
        inventory[purl] = f"https://{authority}{parsed.path.rstrip('/')}", digest
    return inventory, source.meta()


def review(approved_path: str, candidate_path: str, limit: int) -> dict:
    if approved_path == candidate_path == "-":
        raise ValueError("Only one dependency inventory may use stdin")
    approved, approved_source = _inventory(approved_path, limit)
    candidate, candidate_source = _inventory(candidate_path, limit)
    findings = []
    for purl, (registry, digest) in sorted(candidate.items()):
        if purl not in approved:
            findings.append({"purl": purl, "reason": "unapproved_package"})
            continue
        expected_registry, expected_digest = approved[purl]
        if registry != expected_registry:
            findings.append({"purl": purl, "reason": "registry_mismatch"})
        if digest != expected_digest:
            findings.append({"purl": purl, "reason": "digest_mismatch"})
    return clean({
        "schema_version": "1.0", "command": "dependency-review",
        "sources": {"approved": approved_source, "candidate": candidate_source},
        "candidate_dependencies": len(candidate),
        "findings": findings,
    })
