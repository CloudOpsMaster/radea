"""Terraform plan facts derived locally, never from model judgment."""

import hashlib
import json
from pathlib import Path

from radea.core.sanitizer import clean

ACTIONS = {
    ("no-op",), ("create",), ("read",), ("update",), ("delete",), ("delete", "create"),
    ("create", "delete"), ("forget",), ("create", "forget"),
}

def _read_plan(path: str, max_bytes: int) -> tuple[dict, str]:
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
    return plan, hashlib.sha256(raw).hexdigest()


def inspect_plan(path: str, max_bytes: int) -> dict:
    plan, sha256 = _read_plan(path, max_bytes)
    changes = plan.get("resource_changes", [])
    if not isinstance(changes, list) or len(changes) > 50000:
        raise ValueError("Invalid Terraform resource_changes")
    destructive = []
    resources = []
    for entry in changes:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise ValueError("Invalid Terraform resource address")
        change = entry.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if not isinstance(actions, list) or any(not isinstance(a, str) for a in actions):
            raise ValueError("Invalid Terraform action list")
        if tuple(actions) not in ACTIONS:
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
        "sha256": sha256,
        "resources": resources,
        "destructive_actions": destructive,
        "unknown_values_present": any(
            bool(r.get("change", {}).get("after_unknown")) for r in changes
        ),
    }


def inspect_drift(path: str, max_bytes: int) -> dict:
    """Extract recorded refresh drift, withholding before and after attribute values."""
    plan, sha256 = _read_plan(path, max_bytes)
    entries = plan.get("resource_drift", [])
    if not isinstance(entries, list) or len(entries) > 50000:
        raise ValueError("Invalid Terraform resource_drift")
    drift = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
            raise ValueError("Invalid Terraform drift resource address")
        change = entry.get("change")
        actions = change.get("actions") if isinstance(change, dict) else None
        if actions not in (["no-op"], ["create"], ["update"], ["delete"]):
            raise ValueError("Unsupported Terraform refresh drift action")
        if actions != ["no-op"]:
            drift.append({"address": entry["address"], "action": actions[0]})
    incomplete = plan.get("complete") is False or bool(plan.get("deferred_changes"))
    return {
        "schema_version": "1.0",
        "command": "tf-drift",
        "sha256": sha256,
        "incomplete": incomplete,
        "drift": sorted(drift, key=lambda item: (item["address"], item["action"])),
    }


def compare_plans(baseline: str, candidate: str, max_bytes: int) -> dict:
    """Compare planned resource actions and top-level fields while withholding values."""
    reports = []
    for path in (baseline, candidate):
        plan, digest = _read_plan(path, max_bytes)
        entries = plan.get("resource_changes")
        if not isinstance(entries, list) or len(entries) > 50_000:
            raise ValueError("Expected resource_changes in both Terraform plans")
        resources = {}
        incomplete = plan.get("complete") is False or bool(plan.get("deferred_changes"))
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("address"), str):
                raise ValueError("Invalid Terraform resource address")
            address, change = entry["address"], entry.get("change")
            if not address or address in resources or not isinstance(change, dict):
                raise ValueError("Terraform resource changes require unique addresses")
            actions, after, unknown, sensitive = (
                change.get(key) for key in ("actions", "after", "after_unknown", "after_sensitive")
            )
            if (
                not isinstance(actions, list)
                or not all(isinstance(action, str) for action in actions)
                or tuple(actions) not in ACTIONS
                or (after is not None and not isinstance(after, dict))
                or (unknown is not None and not isinstance(unknown, (dict, bool)))
            ):
                raise ValueError("Invalid Terraform planned value")
            # Nested unknown markers may contain false leaves after Terraform normalizes them.
            pending = [unknown]
            while pending:
                marker = pending.pop()
                if marker is True:
                    incomplete = True
                    break
                if isinstance(marker, dict):
                    pending.extend(marker.values())
                if isinstance(marker, list):
                    pending.extend(marker)
            values = {
                key: json.dumps(value, sort_keys=True, allow_nan=False)
                for key, value in after.items()
            } if after is not None else None
            identity_change = (entry.get("previous_address"), change.get("importing"))
            resources[address] = (actions, values, unknown, sensitive, identity_change)
        reports.append((digest, resources, incomplete))
    (before_digest, old, before_incomplete), (after_digest, new, after_incomplete) = reports
    changes = []
    for address in sorted(old.keys() | new.keys()):
        previous, current = old.get(address), new.get(address)
        if previous == current:
            continue
        if previous is None or current is None:
            changes.append({
                "address": address, "change": "added" if previous is None else "removed",
            })
            continue
        old_values, new_values = previous[1] or {}, current[1] or {}
        # Report counts rather than keys because attributes can be sensitive map keys.
        changed_fields = sum(
            key not in old_values or key not in new_values or old_values[key] != new_values[key]
            for key in old_values.keys() | new_values.keys()
        )
        changes.append({
            "address": address, "change": "modified", "changed_fields": changed_fields,
            "actions_changed": previous[0] != current[0],
            "unknowns_changed": previous[2] != current[2],
            "sensitivity_changed": previous[3] != current[3],
            "resource_identity_changed": previous[4] != current[4],
        })
    return clean({
        "schema_version": "1.0", "command": "tf-plan-diff",
        "baseline_sha256": before_digest, "candidate_sha256": after_digest,
        "incomplete": before_incomplete or after_incomplete, "changes": changes,
    })
