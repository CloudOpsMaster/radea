"""Aggregate offline CI failure signatures across bounded log snapshots."""

from collections import Counter

from radea.core.offline import COMPILED
from radea.core.sanitizer import clean
from radea.static_review.files import collect

CATEGORIES = sorted({rule.category for rule, _ in COMPILED})
MAX_LINES = 20_000
MAX_LINE_LENGTH = 2000


def observe(paths: tuple[str, ...], limit: int, threshold: int) -> dict:
    if paths.count("-") > 1:
        raise ValueError("Only one log may use stdin")
    sources, skipped = collect(
        paths, suffixes=(".log",), max_bytes=limit, max_total_bytes=limit,
    )
    if not sources:
        raise ValueError("Expected at least one CI log")
    counts: Counter[str] = Counter()
    clipped = 0
    inspected = 0
    for source in sources:
        inspected += len(source.lines)
        if inspected > MAX_LINES:
            raise ValueError("CI log snapshot exceeds 20000 lines")
        for line in source.lines:
            clipped += len(line) > MAX_LINE_LENGTH
            sample = line[:MAX_LINE_LENGTH]
            counts.update({rule.category for rule, pattern in COMPILED if pattern.search(sample)})
    return clean({
        "schema_version": "1.0", "command": "ci-observe",
        "sources": [source.meta() for source in sources], "skipped": skipped,
        "lines": inspected, "clipped_lines": clipped, "threshold": threshold,
        "categories": [
            {"metric": name, "lines": counts[name], "anomaly": counts[name] >= threshold}
            for name in CATEGORIES
        ],
    })
