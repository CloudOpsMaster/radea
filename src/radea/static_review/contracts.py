"""Compare exact contract revisions across local repository snapshots."""

import json
import re

from radea.core.sanitizer import clean
from radea.static_review.files import collect

LABEL = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}\Z")
REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}\Z")


def check(paths: tuple[str, ...], limit: int) -> dict:
    if not 1 <= len(paths) <= 30 or paths.count("-") > 1:
        raise ValueError("Use one to thirty manifest files and at most one stdin")
    reports = []
    repository_names = set()
    providers: dict[str, tuple[str, str]] = {}
    consumers = []
    bytes_left = limit
    for path in paths:
        if bytes_left <= 0:
            raise ValueError("Contract manifests exceed the input byte limit")
        sources, _ = collect([path], max_bytes=bytes_left)
        if len(sources) != 1:
            raise ValueError("Expected one contract manifest per argument")
        source = sources[0]
        bytes_left -= len(source.text.encode())
        try:
            data = json.loads(source.text)
        except (ValueError, RecursionError):
            raise ValueError("Invalid repository contract JSON") from None
        if not isinstance(data, dict):
            raise ValueError("Expected a repository contract object")
        repository = data.get("repository")
        if not isinstance(repository, str) or not LABEL.fullmatch(repository):
            raise ValueError("Expected a repository identifier")
        if repository in repository_names:
            raise ValueError("Repository identifiers must be unique")
        repository_names.add(repository)
        for field in ("provides", "requires"):
            contracts = data.get(field, {})
            if not isinstance(contracts, dict) or len(contracts) > 1000:
                raise ValueError(f"Expected at most 1000 contracts in {field}")
            for name, revision in contracts.items():
                if (
                    not LABEL.fullmatch(name)
                    or not isinstance(revision, str) or not REVISION.fullmatch(revision)
                ):
                    raise ValueError("Expected contract identifiers and exact revisions")
                if field == "requires":
                    consumers.append((repository, name, revision))
                else:
                    if name in providers:
                        raise ValueError("Each contract must have exactly one declared provider")
                    providers[name] = repository, revision
        reports.append({**source.meta(), "repository": repository})

    findings = []
    for repository, name, expected in sorted(consumers):
        provider, actual = providers.get(name, (None, None))
        if actual != expected:
            findings.append({
                "consumer": repository, "contract": name, "provider": provider,
                "expected": expected, "actual": actual,
                "reason": "missing_provider" if provider is None else "revision_mismatch",
            })
    return clean({
        "schema_version": "1.0", "command": "repo-contract-check", "sources": reports,
        "providers": len(providers), "requirements": len(consumers), "findings": findings,
    })
