"""Deterministic comparison of supplied numbers; no inferred historical baseline."""

import json
import math
import re
from pathlib import Path


def compare(path: str, window: str, maximum: int) -> list[dict]:
    with Path(path).open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("Metrics input exceeds byte limit")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("baseline"), dict):
        raise ValueError("Metrics must contain a baseline object")
    baseline = data.get("baseline", {})
    current = data.get("current")
    values = baseline.get("values")
    if (
        baseline.get("window") != window
        or not isinstance(values, dict)
        or not isinstance(current, dict)
    ):
        raise ValueError("Supply matching baseline.window, baseline.values and current metrics")
    if not values or len(values) > 100 or values.keys() != current.keys():
        raise ValueError("Metrics must have matching sets of 1–100 keys")
    result = []
    for name, before in values.items():
        after = current[name]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            raise ValueError("Invalid metric name")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (before, after)):
            raise ValueError("Metrics must be finite numbers")
        result.append(
            {
                "metric": name,
                "baseline": before,
                "current": after,
                "delta": after - before,
                "change_percent": (after - before) / abs(before) * 100 if before else None,
                "interpretation": "requires_human_review",
            }
        )
    return result
