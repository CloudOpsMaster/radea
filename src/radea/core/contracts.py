"""Validate model structure and evidence independently of model instructions."""

import copy


class ContractError(ValueError):
    pass


def text(value, key):
    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
        raise ContractError(f"Invalid text field: {key}")


def items(value, key):
    if not isinstance(value, list) or len(value) > 100:
        raise ContractError(f"Invalid list field: {key}")
    if any(not isinstance(item, dict) for item in value):
        raise ContractError(f"Invalid object in: {key}")
    return value


def validate(kind: str, data: dict, evidence: dict[str, str]) -> dict:
    result = copy.deepcopy(data)
    if not isinstance(result, dict):
        raise ContractError("Response must be an object")
    if "error" in result:
        raise ContractError("Provider returned an error")

    def references(entry):
        ids = entry.get("evidence_ids")
        if not isinstance(ids, list) or not ids or len(ids) > 32:
            raise ContractError("Every claim needs evidence_ids")
        if any(not isinstance(ref, str) or ref not in evidence for ref in ids):
            raise ContractError("Evidence does not exist in supplied sources")
        if "source_line" in entry and entry["source_line"] not in [evidence[ref] for ref in ids]:
            raise ContractError("Source quote does not match evidence")

    if kind == "debug":
        if result.get("category") not in {
            "code_error",
            "dependency_drift",
            "config_issue",
            "flaky_infra",
            "unknown",
        }:
            raise ContractError("Invalid failure category")
        for entry in items(result.get("hypotheses"), "hypotheses"):
            for key in ("title", "description", "verify"):
                text(entry.get(key), key)
            if entry.get("confidence") not in {"high", "medium", "low"}:
                raise ContractError("Invalid confidence")
            references(entry)
    elif kind == "iac-review":
        text(result.get("summary"), "summary")
        for entry in items(result.get("findings"), "findings"):
            for key in ("title", "description", "resource"):
                text(entry.get(key), key)
            if entry.get("severity") not in {"high", "medium", "low", "info"}:
                raise ContractError("Invalid severity")
            references(entry)
        # Model assertions about destruction are never authoritative.
        result.pop("destructive_actions", None)
    elif kind == "triage":
        for entry in items(result.get("patterns"), "patterns"):
            for key in ("label", "description", "example_line"):
                text(entry.get(key), key)
            if entry.get("severity") not in {"high", "medium", "low"}:
                raise ContractError("Invalid severity")
            if type(entry.get("count")) is not int or entry["count"] < 1:
                raise ContractError("Invalid pattern count")
            references(entry)
            if entry["example_line"] not in [evidence[ref] for ref in entry["evidence_ids"]]:
                raise ContractError("Pattern example must match evidence")
            entry["count_is_estimate"] = True
        for entry in items(result.get("timeline"), "timeline"):
            for key in ("time", "event", "source_line"):
                text(entry.get(key), key)
            references(entry)
        text(result.get("probable_cause"), "probable_cause")
        text(result.get("postmortem_draft"), "postmortem_draft")
        result["cause_status"] = "unverified_hypothesis"
        result["human_conclusion"] = None
        result["action_items"] = []
    else:
        raise ContractError("Unknown command contract")
    allowed = {
        "debug": {"category", "hypotheses"},
        "iac-review": {"summary", "findings"},
        "triage": {
            "patterns",
            "timeline",
            "probable_cause",
            "postmortem_draft",
            "cause_status",
            "human_conclusion",
            "action_items",
        },
    }
    return {key: value for key, value in result.items() if key in allowed[kind]}
