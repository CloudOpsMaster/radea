"""Score recorded draft outputs against explicit expectations, without inference."""

import argparse
import json
from pathlib import Path

from radea.core.contracts import validate


def score(cases: list[dict], responses: Path) -> dict:
    rows = []
    for case in cases:
        path = responses / (case["id"] + ".json")
        if not path.is_file():
            rows.append({"id": case["id"], "status": "missing_response"})
            continue
        if path.stat().st_size > 1_048_576:
            rows.append({"id": case["id"], "status": "oversized_response"})
            continue
        try:
            data = json.loads(path.read_text())
        except ValueError:
            rows.append({"id": case["id"], "status": "invalid_json"})
            continue
        if not isinstance(data, dict):
            rows.append({"id": case["id"], "status": "invalid_object"})
            continue
        try:
            validate(case["command"], data, data.get("evidence", {}))
            valid = (
                data.get("draft") is True
                and data.get("verified") is False
                and not data.get("error")
            )
        except (ValueError, TypeError):
            valid = False
        actions = data.get("destructive_actions", [])
        observed = set()
        if isinstance(actions, list):
            observed = {
                entry["resource"]
                for entry in actions
                if isinstance(entry, dict) and isinstance(entry.get("resource"), str)
            }
        expected = set(case["expected_destructive_resources"])
        rows.append(
            {
                "id": case["id"],
                "status": "scored",
                "contract_valid": valid,
                "missed_destructive_resources": sorted(expected - observed),
                "extra_destructive_resources": sorted(observed - expected),
                "category_match": data.get("category") == case.get("expected_category")
                if "expected_category" in case
                else None,
            }
        )
    return {
        "mode": "recorded_outputs_no_inference",
        "cases": rows,
        "limitations": [
            "Evidence membership is not causal accuracy.",
            "No productivity improvement is measured without human timing data.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--responses", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(score(json.loads(args.cases.read_text()), args.responses), indent=2))


if __name__ == "__main__":
    main()
