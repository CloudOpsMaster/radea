"""Terraform plan facts derived locally, never from model judgment."""

import hashlib
import json
from pathlib import Path


def inspect_plan(path: str, max_bytes: int) -> dict:
    with Path(path).open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("Terraform plan exceeds RADEA_MAX_INPUT_BYTES; no partial review allowed")
    try:
        plan = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ValueError("Terraform plan must be valid JSON") from None
    if not isinstance(plan, dict) or not isinstance(plan.get("format_version"), str):
        raise ValueError("Expected terraform show -json with format_version")
    if plan["format_version"].split(".")[0] != "1":
        raise ValueError("Unsupported Terraform plan format")
    if "resource_changes" not in plan and not isinstance(plan.get("planned_values"), dict):
        raise ValueError("Terraform plan is missing resource data")
    if plan.get("errored") is True:
        raise ValueError("Terraform plan contains errors")
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list) or len(changes) > 50000:
        raise ValueError("Invalid Terraform resource_changes")
    destructive = []
    allowed = {
        ("no-op",),
        ("create",),
        ("read",),
        ("update",),
        ("delete",),
        ("delete", "create"),
        ("create", "delete"),
        ("forget",),
        ("create", "forget"),
    }
    resources = []
    for entry in changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise ValueError("Invalid Terraform resource address")
        change = entry.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(actions, list) or any(not isinstance(a, str) for a in actions):
            raise ValueError("Invalid Terraform action list")
        if tuple(actions) not in allowed:
            raise ValueError("Unrecognized Terraform action; refusing to infer safety")
        resources.append({"resource": entry["address"], "actions": actions})
        if "delete" in actions:
            destructive.append(
                {
                    "resource": entry["address"],
                    "action": "replace" if "create" in actions else "destroy",
                    "origin": "terraform_plan",
                }
            )
    return {
        "status": "incomplete"
        if plan.get("complete") is False or plan.get("deferred_changes")
        else "complete",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "resources": resources,
        "destructive_actions": destructive,
        "unknown_values_present": any(
            bool(r.get("change", {}).get("after_unknown")) for r in changes
        ),
    }
