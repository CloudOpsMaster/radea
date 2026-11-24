"""Draft defensive STRIDE review items from an abstract local data-flow model."""

import json
import re

from radea.core.sanitizer import clean
from radea.static_review.files import collect
from radea.static_review.findings import Finding, build_report

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
CONTROLS = (
    "authenticated",
    "integrity_protected",
    "audit_logged",
    "encrypted",
    "rate_limited",
    "authorized",
)


def _identifier(value) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Expected an abstract component, trust zone or flow identifier")
    return value


def _records(document: dict, field: str) -> list[dict]:
    records = document.get(field)
    if (
        not isinstance(records, list)
        or not 1 <= len(records) <= 500
        or not all(isinstance(record, dict) for record in records)
    ):
        raise ValueError(f"Expected 1–500 {field} records")
    return records


def _input(path: str, max_bytes: int) -> tuple[dict, dict]:
    sources, _ = collect([path], max_bytes=max_bytes)
    if len(sources) != 1:
        raise ValueError("Expected one threat model input")
    source = sources[0]
    try:
        document = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid threat model JSON") from None
    if not isinstance(document, dict):
        raise ValueError("Expected a threat model JSON object")
    return document, source.meta()


def review(path: str, max_bytes: int) -> dict:
    document, source = _input(path, max_bytes)
    zones = {}
    for component in _records(document, "components"):
        name = _identifier(component.get("id"))
        if name in zones:
            raise ValueError("Duplicate component identifier")
        zones[name] = _identifier(component.get("zone"))

    findings = []
    seen = set()
    for flow in _records(document, "flows"):
        name = _identifier(flow.get("id"))
        origin = _identifier(flow.get("from"))
        target = _identifier(flow.get("to"))
        if name in seen or origin not in zones or target not in zones:
            raise ValueError("Flow IDs must be unique and reference existing components")
        seen.add(name)
        if not all(type(flow.get(flag, False)) is bool for flag in ("writes", "sensitive")):
            raise ValueError("Flow attributes must be boolean")
        controls = flow.get("controls", {})
        if not isinstance(controls, dict) or any(
            key not in CONTROLS or type(value) is not bool for key, value in controls.items()
        ):
            raise ValueError("Flow controls must use known boolean fields")
        crosses_boundary = zones[origin] != zones[target]
        writes = flow.get("writes", False)
        required = (
            crosses_boundary,
            crosses_boundary or writes,
            writes,
            crosses_boundary or flow.get("sensitive", False),
            crosses_boundary,
            crosses_boundary or writes,
        )
        for number, (needed, control) in enumerate(zip(required, CONTROLS), start=1):
            if needed and controls.get(control) is not True:
                state = "disabled" if control in controls else "unconfirmed"
                findings.append(
                    Finding(
                        f"TH{number:03d}",
                        name,
                        source["path"],
                        evidence=f"{origin} -> {target}",
                        detail=f"{control} is {state}",
                    )
                )
    report = build_report(
        "threat-review",
        findings,
        [source],
        limitations="Draft review of declared flows and controls. Validate controls and "
        "investigate architecture-specific abuse cases before accepting risk.",
        summary_extra={"components": len(zones), "flows": len(seen)},
    )
    report["draft"] = True
    return report


def dispositions(draft_path: str, decisions_path: str, max_bytes: int) -> dict:
    if draft_path == decisions_path == "-":
        raise ValueError("Only one threat review input may use stdin")
    draft, source = _input(draft_path, max_bytes)
    decisions, review_source = _input(decisions_path, max_bytes)
    if (
        draft.get("command") != "threat-review"
        or draft.get("draft") is not True
        or not isinstance(draft.get("summary"), dict)
        or draft["summary"].get("truncated") is not False
    ):
        raise ValueError("Expected a complete RADEA threat-review draft")
    if decisions.get("draft_sha256") != source["sha256"]:
        raise ValueError("Decisions must identify the exact threat draft SHA-256")
    findings = draft.get("findings")
    if not isinstance(findings, list) or len(findings) > 1000:
        raise ValueError("Invalid threat findings")
    expected = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("Invalid threat finding")
        rule, target = finding.get("rule"), finding.get("target")
        if not isinstance(rule, str) or not re.fullmatch(r"TH00[1-6]", rule):
            raise ValueError("Invalid threat rule")
        if not isinstance(target, str) or not target or len(target) > 64:
            raise ValueError("Invalid threat target")
        expected.add((rule, target))
    if len(expected) != len(findings) or len(expected) != draft["summary"].get("findings"):
        raise ValueError("Threat draft findings are missing or ambiguous")

    rows = decisions.get("decisions")
    if not isinstance(rows, list) or len(rows) > len(expected):
        raise ValueError("Expected at most one decision per finding")
    recorded = set()
    items = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"rule", "target", "status", "owner", "reason"}:
            raise ValueError("Each decision needs a rule, target, status, owner and reason")
        if any(not isinstance(value, str) or not value.strip() for value in row.values()):
            raise ValueError("Decision fields must be nonempty strings")
        identity = (row["rule"], row["target"])
        if identity not in expected or identity in recorded:
            raise ValueError("Decision references an unknown or repeated finding")
        if row["status"] not in ("accept", "mitigate", "monitor", "dismiss"):
            raise ValueError("Expected accept, mitigate, monitor or dismiss")
        if len(row["owner"]) > 128 or len(row["reason"]) > 2000:
            raise ValueError("Threat decision owner or rationale exceeds the limit")
        recorded.add(identity)
        items.append(row)
    return clean({
        "schema_version": "1.0",
        "command": "threat-disposition",
        "sources": {"draft": source, "decisions": review_source},
        "decisions": items,
        "pending": [
            {"rule": rule, "target": target} for rule, target in sorted(expected - recorded)
        ],
    })
