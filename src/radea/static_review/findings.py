"""Findings, report assembly, text rendering and the CI exit-code contract."""

from dataclasses import dataclass

from radea.core.sanitizer import clean, sanitize
from radea.static_review.catalog import CATALOG

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}
FAIL_ON = ("high", "medium", "low", "never")
MAX_FINDINGS = 1000
SCHEMA_VERSION = "1.0"
ANALYSIS_VERSION = "static-v1"


@dataclass(frozen=True)
class Finding:
    rule: str
    target: str  # resource, job, stage or package the finding is about
    path: str
    line: int | None = None
    evidence: str = ""  # a quote of the offending line, or a neutral description
    detail: str = ""  # instance-specific context such as the container name


def quote(text: str, limit: int = 200) -> str:
    """One-line, bounded, secret-redacted quote of a source line."""
    return sanitize(" ".join(text.split())[:limit]).text


def _as_dict(finding: Finding) -> dict:
    rule = CATALOG[finding.rule]
    return {
        "rule": finding.rule,
        "severity": rule.severity,
        "title": rule.title,
        "target": finding.target,
        "path": finding.path,
        "line": finding.line,
        "evidence": finding.evidence,
        "detail": finding.detail,
        "why": rule.why,
        "fix": rule.fix,
        "articles": list(rule.articles),
    }


def build_report(
    command: str,
    findings: list[Finding],
    sources: list[dict],
    *,
    skipped: list[dict] | None = None,
    limitations: str = "",
) -> dict:
    unique = {(f.rule, f.target, f.path, f.line, f.detail): f for f in findings}
    ordered = sorted(
        unique.values(),
        key=lambda f: (
            SEVERITY_ORDER[CATALOG[f.rule].severity],
            f.path,
            f.line or 0,
            f.rule,
            f.target,
        ),
    )
    shown = ordered[:MAX_FINDINGS]
    by_severity = {name: 0 for name in SEVERITY_ORDER}
    for finding in ordered:
        by_severity[CATALOG[finding.rule].severity] += 1
    report = {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "analysis_origin": "deterministic_rules",
        "analysis_version": ANALYSIS_VERSION,
        "draft": False,
        "summary": {
            "files": len(sources),
            "findings": len(ordered),
            "by_severity": by_severity,
            "truncated": len(ordered) > len(shown),
        },
        "findings": [_as_dict(finding) for finding in shown],
        "sources": sources,
        "skipped": skipped or [],
        "limitations": limitations
        or "Static rules only. No findings does not prove the configuration is safe.",
    }
    return clean(report)


def exit_code(report: dict, fail_on: str) -> int:
    """0 clean at the chosen threshold, 2 findings at or above it (same as policy-check)."""
    if fail_on == "never":
        return 0
    limit = SEVERITY_ORDER[fail_on]
    return 2 if any(SEVERITY_ORDER[item["severity"]] <= limit for item in report["findings"]) else 0


def render_text(report: dict) -> str:
    summary = report["summary"]
    counts = ", ".join(f"{n} {name}" for name, n in summary["by_severity"].items() if n)
    lines = [
        f"RADEA {report['command']}: {summary['findings']} finding(s) in "
        f"{summary['files']} file(s)" + (f" ({counts})" if counts else ""),
    ]
    for item in report["findings"]:
        where = item["path"] + (f":{item['line']}" if item["line"] else "")
        extra = f" [{item['detail']}]" if item["detail"] else ""
        lines.append(f"{item['severity'].upper():6} {item['rule']} {where} {item['target']}{extra}")
        lines.append(f"       {item['title']}")
        if item["evidence"]:
            lines.append(f"       > {item['evidence']}")
        lines.append(f"       fix: {item['fix']}")
    if summary["truncated"]:
        lines.append(f"... output limited to {MAX_FINDINGS} findings")
    for item in report["skipped"]:
        lines.append(f"skipped {item['path']}: {item['reason']}")
    lines.append(report["limitations"])
    return "\n".join(lines)
