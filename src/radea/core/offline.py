"""Bounded rule analysis of sanitized evidence; no network or inference dependencies."""

import json
import re
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    category: str
    pattern: str
    advice: str
    severity: str = "medium"


RULES = (
    Rule(
        "Missing dependency",
        "dependency_drift",
        r"ModuleNotFoundError:|ImportError:|No matching distribution found|Cannot find module",
        "Compare the installed dependencies and lockfile with the failing interpreter.",
    ),
    Rule(
        "Syntax failure",
        "code_error",
        r"SyntaxError:|IndentationError:|TabError:",
        "Compile the cited source with the same language version used by the job.",
    ),
    Rule(
        "Runtime exception",
        "code_error",
        r"(?:TypeError|NameError|AttributeError|ZeroDivisionError|KeyError|IndexError):",
        "Reproduce the cited exception and inspect its traceback and inputs.",
    ),
    Rule(
        "Permission failure",
        "config_issue",
        r"PermissionError:|permission denied|access denied",
        "Check the effective user and the minimum permissions required for this operation.",
    ),
    Rule(
        "Missing file",
        "config_issue",
        r"FileNotFoundError:|IsADirectoryError:|NotADirectoryError:|no such file or directory",
        "Check the working directory, expected file and upstream artifact availability.",
    ),
    Rule(
        "Memory limit signal",
        "flaky_infra",
        r"\bOOMKilled\b|out of memory|MemoryError:",
        "Inspect measured peak memory and the configured job/container memory limit.",
        "high",
    ),
    Rule(
        "Timeout signal",
        "flaky_infra",
        r"\btimed out\b|\bTimeoutError\b|TimeoutExpired:|deadline exceeded",
        "Check request latency and service health; a timeout alone does not establish cause.",
    ),
    Rule(
        "Connection failure",
        "flaky_infra",
        r"connection refused|ConnectionRefusedError:",
        "Check the endpoint and service readiness from the same runner network.",
    ),
)
COMPILED = tuple((rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in RULES)
STAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")


def matches(evidence: dict[str, str]) -> dict:
    groups = defaultdict(list)
    for ref, line in evidence.items():
        for rule, pattern in COMPILED:
            if pattern.search(line):
                groups[rule].append((ref, line))
    return groups


def analyze(kind: str, evidence: dict[str, str]) -> dict:
    """Claims describe observed signals, never assert an inferred root cause."""
    groups = matches(evidence)
    if kind == "debug":
        categories = {rule.category for rule in groups}
        return {
            "category": next(iter(categories)) if len(categories) == 1 else "unknown",
            "hypotheses": [
                {
                    "title": rule.name,
                    "description": "Observed log signal; cause is unverified.",
                    "verify": rule.advice,
                    "confidence": "low",
                    "source_line": rows[0][1],
                    "evidence_ids": [rows[0][0]],
                }
                for rule, rows in groups.items()
            ],
        }
    if kind == "iac-review":
        findings = []
        for ref, line in evidence.items():
            resource = json.loads(line) if ref.startswith("plan:") else None
            if resource and "delete" in resource["actions"]:
                findings.append(
                    {
                        "title": "Destructive plan action",
                        "severity": "high",
                        "description": "Plan includes deletion; review the policy gate.",
                        "resource": resource["resource"],
                        "evidence_ids": [ref],
                    }
                )
        return {
            "summary": "Local checks only: plan deletion signals and literal IAM wildcards. "
            "No findings does not mean the configuration is secure.",
            "findings": findings[:100],
        }
    timeline = []
    for ref, line in evidence.items():
        stamp = STAMP.search(line)
        if stamp and any(pattern.search(line) for _, pattern in COMPILED):
            timeline.append(
                {
                    "time": stamp[0],
                    "event": "Observed failure signal",
                    "source_line": line,
                    "evidence_ids": [ref],
                }
            )
    return {
        "patterns": [
            {
                "label": rule.name,
                "description": rule.advice,
                "severity": rule.severity,
                "count": len(rows),
                "example_line": rows[0][1],
                "evidence_ids": [rows[0][0]],
            }
            for rule, rows in groups.items()
        ],
        "timeline": timeline[:100],
        "probable_cause": "Unknown; deterministic signals do not establish causation.",
        "postmortem_draft": "Review the cited observations and supplied metric comparisons. "
        "A human must establish impact, cause and follow-up actions.",
    }
