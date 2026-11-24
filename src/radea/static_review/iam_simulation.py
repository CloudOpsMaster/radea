"""Check expected allow and deny cases against an AWS IAM simulation export."""

import json
import re

from radea.static_review.files import collect

ACTIONS = re.compile(r"[A-Za-z0-9-]+:[A-Za-z0-9]+\Z")
DECISIONS = {"allowed", "explicitDeny", "implicitDeny"}


def _load(path: str, limit: int) -> tuple[object, dict]:
    files, _ = collect([path], max_bytes=limit)
    if len(files) != 1:
        raise ValueError("Expected one IAM JSON input file")
    try:
        return json.loads(files[0].text), files[0].meta()
    except (ValueError, RecursionError):
        raise ValueError("Invalid IAM simulation JSON") from None


def _key(action, resource) -> tuple[str, str]:
    if not isinstance(action, str) or len(action) > 128 or not ACTIONS.fullmatch(action):
        raise ValueError("Expected a concrete IAM action")
    if not isinstance(resource, str) or not resource.strip() or len(resource) > 2048:
        raise ValueError("Expected a concrete IAM resource or wildcard")
    return action.lower(), resource


def review(export: str, examples: str, limit: int) -> dict:
    if export == examples == "-":
        raise ValueError("Only one IAM simulation input may use stdin")
    document, source = _load(export, limit)
    cases, case_source = _load(examples, limit)
    if not isinstance(document, dict) or document.get("IsTruncated") is True:
        raise ValueError("Expected a complete IAM simulation export")
    results = document.get("EvaluationResults")
    if not isinstance(results, list) or len(results) > 10_000:
        raise ValueError("Expected bounded IAM EvaluationResults")
    observed = {}
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Invalid IAM evaluation")
        nested = result.get("ResourceSpecificResults", [])
        if not isinstance(nested, list):
            raise ValueError("Invalid resource-level IAM evaluation")
        decision_field = "EvalResourceDecision" if nested else "EvalDecision"
        for row in nested or [result]:
            if not isinstance(row, dict):
                raise ValueError("Invalid IAM resource result")
            identity = _key(result.get("EvalActionName"), row.get("EvalResourceName"))
            decision, missing = row.get(decision_field), row.get("MissingContextValues", [])
            if (
                identity in observed or not isinstance(decision, str) or decision not in DECISIONS
                or not isinstance(missing, list) or not all(isinstance(key, str) for key in missing)
            ):
                raise ValueError("Invalid or duplicate IAM simulation result")
            observed[identity] = "unknown" if missing else decision
    if not isinstance(cases, list) or not 1 <= len(cases) <= 1000:
        raise ValueError("Expected 1–1000 IAM expectation cases")
    outcomes = []
    for number, case in enumerate(cases, 1):
        if not isinstance(case, dict) or case.get("expect") not in ("allow", "deny"):
            raise ValueError(f"Expected an allow or deny case at position {number}")
        identity = _key(case.get("action"), case.get("resource"))
        actual = observed.get(identity, "unknown")
        expected = case["expect"]
        ok = actual != "unknown" and (actual == "allowed") == (expected == "allow")
        outcomes.append({"case": number, "expected": expected, "simulated": actual, "passed": ok})
    return {
        "schema_version": "1.0", "command": "iam-simulation-review",
        "sources": {"simulation": source, "expectations": case_source},
        "cases": outcomes, "passed": all(case["passed"] for case in outcomes),
    }
