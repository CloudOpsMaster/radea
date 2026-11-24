"""Track reference-based secret migration from metadata and recorded checks."""

import json
import re

from radea.core.sanitizer import clean
from radea.static_review.files import collect

LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
CHECKS = ("rotation_verified", "legacy_removed", "plaintext_scan_clean")
FIELDS = {"id", "owner", "reference", "consumers", "verified_consumers", *CHECKS}


def _label(value) -> bool:
    return isinstance(value, str) and LABEL.fullmatch(value) is not None


def plan(path: str, limit: int) -> dict:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one migration metadata file")
    source = sources[0]
    try:
        document = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid secret migration metadata") from None
    records = document.get("secrets") if isinstance(document, dict) else None
    if not isinstance(records, list) or not 1 <= len(records) <= 500:
        raise ValueError("Expected 1–500 secret metadata records")
    seen = set()
    items = []
    for number, row in enumerate(records, 1):
        if not isinstance(row, dict) or set(row) - FIELDS:
            raise ValueError(f"Unknown metadata field at position {number}")
        identity, owner, reference = (row.get(key) for key in ("id", "owner", "reference"))
        if (
            not _label(identity) or not _label(owner) or identity in seen
            or (reference is not None and not _label(reference))
        ):
            raise ValueError(f"Invalid or duplicate metadata identifier at position {number}")
        seen.add(identity)
        consumers, verified = row.get("consumers"), row.get("verified_consumers", [])
        if not all(
            isinstance(values, list) and len(values) <= 100 and all(_label(v) for v in values)
            and len(values) == len(set(values))
            for values in (consumers, verified)
        ) or not consumers or set(verified) - set(consumers):
            raise ValueError(f"Invalid consumer list at position {number}")
        if any(type(row.get(key, False)) is not bool for key in CHECKS):
            raise ValueError(f"Migration checks must be booleans at position {number}")
        missing = sorted(set(consumers) - set(verified))
        pending = [
            *(["configure_reference"] if reference is None else []),
            *(["verify_consumers"] if missing else []),
            *(key for key in CHECKS if not row.get(key, False)),
        ]
        items.append({
            "id": identity, "owner": owner, "unverified_consumers": missing, "pending": pending,
        })
    return clean({
        "schema_version": "1.0", "command": "secret-migration-plan", "source": source.meta(),
        "ready": all(not item["pending"] for item in items), "items": items,
    })
