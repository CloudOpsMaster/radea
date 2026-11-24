"""Run local ShellCheck without executing scripts and compare diagnostic counts."""

import json
import os
import subprocess
from collections import Counter
from tempfile import TemporaryDirectory

from radea.core.sanitizer import clean
from radea.static_review.files import Source, collect


def _source(path: str, limit: int) -> Source:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one shell script")
    return sources[0]


def _check(source: Source, dialect: str | None) -> list[dict]:
    arguments = ["shellcheck", "--norc", "--format=json"]
    if dialect:
        arguments.append(f"--shell={dialect}")
    arguments.append("-")
    env = {key: value for key, value in os.environ.items() if key != "SHELLCHECK_OPTS"}
    with TemporaryDirectory(prefix="radea-shell-") as work:
        result = subprocess.run(
            arguments,
            input=source.text.encode(),
            capture_output=True,
            cwd=work,
            env=env,
            timeout=20,
            check=False,
        )
    if result.returncode not in (0, 1):
        raise ValueError("ShellCheck could not analyze the supplied script")
    try:
        diagnostics = json.loads(result.stdout)
    except (ValueError, RecursionError):
        raise ValueError("ShellCheck returned invalid JSON") from None
    if not isinstance(diagnostics, list):
        raise ValueError("Expected ShellCheck JSON diagnostics")
    return [
        {key: item[key] for key in ("line", "column", "level", "code", "message")}
        for item in diagnostics
    ]


def _identity(item: dict) -> tuple:
    return item["level"], item["code"], item["message"]


def review(path: str, baseline: str | None, dialect: str | None, limit: int) -> dict:
    if path == baseline == "-":
        raise ValueError("Only one script may use stdin")
    candidate = _source(path, limit)
    diagnostics = _check(candidate, dialect)
    old = _source(baseline, limit) if baseline is not None else None
    previous = Counter(_identity(item) for item in _check(old, dialect)) if old else Counter()
    introduced = []
    for item in diagnostics:
        identity = _identity(item)
        if previous[identity]:
            previous[identity] -= 1
        else:
            introduced.append(item)
    return clean(
        {
            "schema_version": "1.0",
            "command": "shell-review",
            "source": candidate.meta(),
            "baseline": old.meta() if old else None,
            "diagnostics": diagnostics,
            "introduced": introduced,
            "resolved_count": sum(previous.values()),
        }
    )
