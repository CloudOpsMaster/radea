"""Small auditable policy rules. No model decides allow/deny."""

import re


def iam_findings(evidence: dict[str, str]) -> list[dict]:
    findings = []
    for ref, line in evidence.items():
        for field in ("Action", "Resource"):
            if re.search(r"\b" + field + r"""["']?\s*[:=]\s*(?:\[\s*)?["']\*["']""", line):
                findings.append(
                    {
                        "severity": "high",
                        "title": f"IAM {field} wildcard requires review",
                        "resource": ref,
                        "description": "Literal wildcard found; verify scope and least privilege.",
                        "evidence_ids": [ref],
                        "origin": "local_literal_rule",
                    }
                )
    return findings


def destruction_policy(facts: dict, allow_destruction: bool = False) -> dict:
    if facts["status"] != "complete":
        return {"policy_version": "1", "decision": "deny", "reason": "Incomplete Terraform plan"}
    denied = bool(facts["destructive_actions"]) and not allow_destruction
    return {
        "policy_version": "1",
        "decision": "deny" if denied else "allow",
        "reason": "Destructive actions require explicit approval"
        if denied
        else "No prohibited actions",
        "destructive_actions": facts["destructive_actions"],
    }
