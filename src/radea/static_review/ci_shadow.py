"""Compare test outcomes and artifact digests from paired CI executions."""

import json
import re

from radea.core.sanitizer import clean
from radea.static_review.files import collect
from radea.static_review.flaky import parse_run

REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ARTIFACT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _build(path: str, limit: int) -> tuple[str, int, dict[str, str]]:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one build metadata file")
    try:
        data = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid build metadata JSON") from None
    if not isinstance(data, dict):
        raise ValueError("Expected a build metadata object")
    revision, duration, artifacts = (
        data.get("revision"), data.get("duration_ms"), data.get("artifacts")
    )
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ValueError("Build metadata requires a full lowercase Git revision")
    if type(duration) is not int or not 0 <= duration <= 31_536_000_000:
        raise ValueError("Build metadata requires a bounded duration in milliseconds")
    if not isinstance(artifacts, dict) or len(artifacts) > 1000 or any(
        not ARTIFACT.fullmatch(name) or not isinstance(digest, str) or not DIGEST.fullmatch(digest)
        for name, digest in artifacts.items()
    ):
        raise ValueError("Expected up to 1000 named artifact SHA-256 digests")
    return revision, duration, artifacts


def compare(
    baseline: str, candidate: str, limit: int,
    *, baseline_build: str | None = None, candidate_build: str | None = None,
) -> dict:
    if (baseline_build is None) != (candidate_build is None):
        raise ValueError("Supply both baseline and candidate build metadata")
    if (baseline, candidate, baseline_build, candidate_build).count("-") > 1:
        raise ValueError("Only one input may use stdin")
    reports = []
    for path in (baseline, candidate):
        sources, _ = collect([path], max_bytes=limit)
        if len(sources) != 1:
            raise ValueError("Expected one JUnit report per CI run")
        reports.append((sources[0].meta(), parse_run(sources[0], reject_duplicates=True)))
    (before_src, before), (after_src, after) = reports
    changes = []
    for test in sorted(before.keys() | after.keys()):
        previous = before[test][0] if test in before else None
        current = after[test][0] if test in after else None
        if previous != current:
            changes.append({"test": test, "baseline": previous, "candidate": current})
    report = {
        "schema_version": "1.0",
        "command": "ci-shadow",
        "sources": {"baseline": before_src, "candidate": after_src},
        "baseline_tests": len(before),
        "candidate_tests": len(after),
        "changes": changes,
    }
    if baseline_build is not None and candidate_build is not None:
        old_rev, old_duration, old_artifacts = _build(baseline_build, limit)
        new_rev, new_duration, new_artifacts = _build(candidate_build, limit)
        if old_rev != new_rev:
            raise ValueError("Build metadata refers to different Git revisions")
        report["build"] = {
            "revision": old_rev,
            "baseline_duration_ms": old_duration,
            "candidate_duration_ms": new_duration,
            "duration_delta_ms": new_duration - old_duration,
            "artifact_changes": [
                {
                    "artifact": name,
                    "change": (
                        "added" if name not in old_artifacts
                        else "removed" if name not in new_artifacts
                        else "digest_changed"
                    ),
                }
                for name in sorted(old_artifacts.keys() | new_artifacts.keys())
                if old_artifacts.get(name) != new_artifacts.get(name)
            ],
        }
    return clean(report)
