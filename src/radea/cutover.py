"""Validate reversible cutover steps and simulate a failure without executing the plan."""

import json
import re
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect

STEP = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
FIELDS = ("owner", "apply", "verify", "rollback", "verify_rollback")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError(f"Expected nonempty {field} of at most 1000 characters")
    return value.strip()


def plan(path: str, failed_step: str | None, limit: int) -> dict:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one cutover plan")
    try:
        raw = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid cutover plan JSON") from None
    records = raw.get("steps") if isinstance(raw, dict) else None
    if not isinstance(records, list) or not 1 <= len(records) <= 50:
        raise ValueError("Cutover plan requires 1–50 steps")
    steps = []
    seen = set()
    for item in records:
        identity = item.get("id") if isinstance(item, dict) else None
        if not isinstance(identity, str) or not STEP.fullmatch(identity) or identity in seen:
            raise ValueError("Cutover step IDs must be unique lowercase labels")
        seen.add(identity)
        steps.append({"id": identity, **{field: _text(item.get(field), field) for field in FIELDS}})
    if failed_step is not None and failed_step not in seen:
        raise ValueError("Rehearsal must identify a step in the plan")

    events = []
    if failed_step:
        for index, step in enumerate(steps):
            events.append({"step": step["id"], "phase": "apply", "outcome": "simulated"})
            if step["id"] != failed_step:
                events.append({"step": step["id"], "phase": "verify", "outcome": "passed"})
            else:
                events.append({"step": step["id"], "phase": "verify", "outcome": "failed"})
                for applied in reversed(steps[: index + 1]):
                    events.extend(
                        {"step": applied["id"], "phase": phase, "outcome": "simulated"}
                        for phase in ("rollback", "verify_rollback")
                    )
                break
    return clean(
        {
            "schema_version": "1.0",
            "command": "cutover-plan",
            "draft": True,
            "name": _text(raw.get("name"), "name"),
            "steps": steps,
            "simulation": {"failure_step": failed_step, "events": events} if failed_step else None,
        }
    )
