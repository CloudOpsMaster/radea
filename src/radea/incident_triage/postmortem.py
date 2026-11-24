"""Record a human review against a captured triage draft."""

import json
from datetime import date
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ValueError(f"Expected nonempty {field} of at most 4000 characters")
    return value.strip()


def _object(path: str, limit: int) -> tuple[dict, dict]:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected a single JSON file per input")
    try:
        data = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid postmortem JSON input") from None
    if not isinstance(data, dict):
        raise ValueError("Postmortem inputs must be JSON objects")
    return data, sources[0].meta()


def review(draft_path: str, decisions_path: str, limit: int) -> dict:
    if draft_path == decisions_path == "-":
        raise ValueError("Only one postmortem input may use stdin")
    draft, source = _object(draft_path, limit)
    decisions, review_source = _object(decisions_path, limit)
    evidence = draft.get("evidence")
    if (
        draft.get("command") != "triage"
        or draft.get("draft") is not True
        or "error" in draft
        or not isinstance(evidence, dict)
    ):
        raise ValueError("A RADEA triage draft with an evidence map is required")
    if decisions.get("draft_sha256") != source["sha256"]:
        raise ValueError("The review must identify the exact draft SHA-256")
    reviewer = _text(decisions.get("reviewer"), "reviewer")
    conclusion = _text(decisions.get("conclusion"), "conclusion")
    status = decisions.get("cause_status")
    if status not in ("confirmed_by_reviewer", "unknown"):
        raise ValueError("Declare a confirmed or unknown cause")
    references = decisions.get("evidence_ids", [])
    if (
        not isinstance(references, list)
        or len(references) > 32
        or any(not isinstance(ref, str) or ref not in evidence for ref in references)
        or (status == "confirmed_by_reviewer" and not references)
    ):
        raise ValueError("A confirmed cause requires evidence IDs from the draft")
    records = decisions.get("action_items")
    if not isinstance(records, list) or len(records) > 50:
        raise ValueError("Declare up to 50 action items")
    actions = []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Action items must be JSON objects")
        owner, action, due = (_text(item.get(key), key) for key in ("owner", "action", "due"))
        if date.fromisoformat(due).isoformat() != due:
            raise ValueError("Use an action due date in YYYY-MM-DD format")
        actions.append({"owner": owner, "action": action, "due": due})
    return clean(
        {
            "schema_version": "1.0",
            "command": "postmortem-review",
            "status": "human_review_recorded",
            "reviewer": reviewer,
            "cause_status": status,
            "human_conclusion": conclusion,
            "evidence_ids": references,
            "action_items": actions,
            "sources": {"draft": source, "review": review_source},
        }
    )
