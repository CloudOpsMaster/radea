"""Retrieve cited passages from local platform documentation."""

import json
import math
import os
import re
import stat
from collections import Counter

from radea.core.sanitizer import clean, sanitize
from radea.static_review.files import collect

TOPIC = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
WORDS = re.compile(r"[^\W_]+", re.UNICODE)
STOP = set(
    "a an and are as at be by can do does for from how i in is it my of on or should "
    "that the this to use what when where which who with you your як що де чи для це".split()
)


def _tokens(text: str) -> set[str]:
    return {word for word in WORDS.findall(text.casefold()) if len(word) >= 2 and word not in STOP}


def answer(question: str, paths: tuple[str, ...], limit: int, maximum: int) -> dict:
    query = _tokens(sanitize(question).text)
    if not query or len(question) > 500:
        raise ValueError("Question must contain searchable terms and at most 500 characters")
    sources, skipped = collect(paths, suffixes=(".md", ".txt"), max_bytes=min(limit, 262_144))
    if not sources:
        raise ValueError("No readable documentation files")
    candidates = []
    counts: Counter[str] = Counter()
    for source in sources:
        if not source.lines:
            continue
        for offset in range(0, len(source.lines), 8):
            lines = source.lines[offset : offset + 12]
            passage = "\n".join(lines)
            terms = _tokens(passage) & query
            if len(terms) < min(2, len(query)):
                continue
            counts.update(terms)
            candidates.append((source.path, offset + 1, offset + len(lines), passage, terms))
    ranked = sorted(
        candidates,
        key=lambda item: (
            -sum(1 / math.sqrt(counts[term]) for term in sorted(item[4])),
            item[0],
            item[1],
        ),
    )
    citations: list[dict] = []
    for path, start, end, text, _ in ranked:
        if any(
            path == hit["path"] and start <= hit["end_line"] and end >= hit["start_line"]
            for hit in citations
        ):
            continue
        citations.append(
            {
                "path": path,
                "start_line": start,
                "end_line": end,
                "excerpt": sanitize(text).text[:1200],
            }
        )
        if len(citations) >= maximum:
            break
    return clean(
        {
            "schema_version": "1.0",
            "command": "docs-answer",
            "status": "passages_found" if citations else "no_documented_answer",
            "sources_scanned": len(sources),
            "skipped": skipped,
            "citations": citations,
        }
    )


def log_gap(path: str, topic: str) -> None:
    """Retain a caller-chosen category, without retaining the question."""
    if not TOPIC.fullmatch(topic):
        raise ValueError("Gap topic must be a lowercase category with at most 64 characters")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Gap log must be a regular file")
        event = (json.dumps({"topic": topic}) + "\n").encode()
        if os.write(descriptor, event) != len(event):
            raise OSError("Incomplete documentation gap event")
    finally:
        os.close(descriptor)


def backlog(path: str, limit: int) -> dict:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one documentation gap log")
    counts: Counter[str] = Counter()
    for line in sources[0].lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            raise ValueError("Invalid documentation gap event") from None
        topic = event.get("topic") if isinstance(event, dict) else None
        if not isinstance(topic, str) or not TOPIC.fullmatch(topic):
            raise ValueError("Invalid documentation gap topic")
        counts[topic] += 1
    return {
        "schema_version": "1.0",
        "command": "docs-backlog",
        "topics": [
            {"topic": topic, "requests": count}
            for topic, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }
