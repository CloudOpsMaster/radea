"""Check rebuild parity using explicit, value-free inventory differences."""

import json
import re

from radea.core.sanitizer import clean
from radea.static_review.files import collect

CATEGORIES = ("packages", "services", "config_sha256", "probes")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def _inventory(path: str, limit: int) -> tuple[dict[str, dict[str, str]], dict]:
    files, _ = collect([path], max_bytes=limit)
    if len(files) != 1:
        raise ValueError("Expected one infrastructure inventory")
    source = files[0]
    try:
        data = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid infrastructure inventory JSON") from None
    if not isinstance(data, dict) or not data or set(data) - set(CATEGORIES):
        raise ValueError("Expected only package, service, config hash and probe inventories")
    for category, entries in data.items():
        if not isinstance(entries, dict) or len(entries) > 10_000:
            raise ValueError(f"Expected up to 10000 entries in {category}")
        for name, value in entries.items():
            if (
                not name.strip() or len(name) > 200
                or not isinstance(value, str) or not value.strip() or len(value) > 256
                or (category == "config_sha256" and not DIGEST.fullmatch(value))
            ):
                raise ValueError(f"Invalid entry in {category}")
    return data, source.meta()


def compare(baseline: str, rebuilt: str, limit: int) -> dict:
    if baseline == rebuilt == "-":
        raise ValueError("Only one rebuild inventory may use stdin")
    before, old_source = _inventory(baseline, limit)
    after, new_source = _inventory(rebuilt, limit)
    incomplete = [
        category for category in CATEGORIES if (category in before) != (category in after)
    ]
    changes = []
    for category in CATEGORIES:
        old, new = before.get(category, {}), after.get(category, {})
        for name in sorted(old.keys() | new.keys()):
            if old.get(name) == new.get(name):
                continue
            reason = "added" if name not in old else "removed" if name not in new else "changed"
            changes.append({"category": category, "name": name, "change": reason})
    return clean({
        "schema_version": "1.0", "command": "rebuild-check",
        "sources": {"baseline": old_source, "rebuilt": new_source},
        "missing_categories": incomplete, "changes": changes,
        "matches": not incomplete and not changes,
    })
