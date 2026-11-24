"""Evaluate a versioned rollout flag for a caller-supplied cohort and groups."""

import json
import re

from radea.core.sanitizer import clean
from radea.migration import cohort_bucket
from radea.static_review.files import collect

VARIANT = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")


def _document(path: str, limit: int):
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one feature flag file")
    try:
        return json.loads(sources[0].text), sources[0].meta()
    except (ValueError, RecursionError):
        raise ValueError("Invalid feature flag JSON") from None


def evaluate(path: str, flag: str, cohort: str, groups: tuple[str, ...], limit: int) -> dict:
    config, _ = _document(path, limit)
    flags = config.get("flags") if isinstance(config, dict) else None
    if not isinstance(flags, dict) or not 1 <= len(flag) <= 100:
        raise ValueError("Expected flags and a valid flag name")
    bucket = cohort_bucket("flag:" + flag, cohort)
    variant = None
    rule = flags.get(flag)
    if rule is None and flag not in flags:
        enabled, reason = False, "unknown_flag"
    else:
        if not isinstance(rule, dict) or type(rule.get("enabled")) is not bool:
            raise ValueError("Feature flag must declare a boolean enabled state")
        rollout = rule.get("rollout", 100)
        allowed = rule.get("groups", [])
        if type(rollout) is not int or not 0 <= rollout <= 100:
            raise ValueError("Rollout must be an integer percentage")
        if not isinstance(allowed, list) or not all(
            isinstance(item, str) and item for item in allowed
        ):
            raise ValueError("Feature flag groups must be nonempty strings")
        weights = rule.get("variants")
        if weights is not None and (
            not isinstance(weights, dict)
            or not weights
            or not all(
                VARIANT.fullmatch(name) and type(weight) is int and weight > 0
                for name, weight in weights.items()
            )
            or sum(weights.values()) != 100
        ):
            raise ValueError("Variants require positive integer weights summing to 100")
        if not rule["enabled"]:
            enabled, reason = False, "disabled"
        elif allowed and not set(allowed).intersection(groups):
            enabled, reason = False, "group_mismatch"
        else:
            enabled = bucket < rollout
            reason = "in_rollout" if enabled else "outside_rollout"
            if enabled and weights:
                variant_bucket = cohort_bucket("variant:" + flag, cohort)
                for name, weight in sorted(weights.items()):
                    if variant_bucket < weight:
                        variant = name
                        break
                    variant_bucket -= weight
    return {
        "schema_version": "1.0",
        "command": "flag-evaluate",
        "enabled": enabled,
        "reason": reason,
        "variant": variant,
    }


def experiment(path: str, control: str, limit: int) -> dict:
    """Summarize one preassigned outcome per cohort from a single experiment export."""
    if not VARIANT.fullmatch(control):
        raise ValueError("Invalid control variant")
    document, source = _document(path, limit)
    if not isinstance(document, dict) or set(document) != {"experiment", "observations"}:
        raise ValueError("Expected an experiment identifier and observations")
    identifier, rows = document["experiment"], document["observations"]
    if not isinstance(identifier, str) or not VARIANT.fullmatch(identifier):
        raise ValueError("Invalid experiment identifier")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 25_000:
        raise ValueError("Expected 1–25000 experiment observations")

    assignments: dict[str, tuple[str, bool]] = {}
    totals: dict[str, tuple[int, int]] = {}
    duplicates = 0
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or set(row) != {"cohort", "variant", "success"}:
            raise ValueError(f"Invalid observation at position {index}")
        cohort, variant, success = row["cohort"], row["variant"], row["success"]
        if (
            not isinstance(cohort, str) or not cohort.strip() or len(cohort) > 256
            or not isinstance(variant, str) or not VARIANT.fullmatch(variant)
            or type(success) is not bool
        ):
            raise ValueError(f"Invalid observation at position {index}")
        if cohort in assignments:
            if assignments[cohort] != (variant, success):
                raise ValueError(f"Conflicting observation at position {index}")
            duplicates += 1
            continue
        assignments[cohort] = variant, success
        size, successes = totals.get(variant, (0, 0))
        totals[variant] = size + 1, successes + success
        if len(totals) > 16:
            raise ValueError("Expected at most sixteen experiment variants")
    if control not in totals or len(totals) < 2:
        raise ValueError("Expected observations for the control and another variant")

    control_size, control_successes = totals[control]
    return clean({
        "schema_version": "1.0",
        "command": "flag-experiment",
        "source": source,
        "experiment": identifier,
        "control": control,
        "duplicates": duplicates,
        "variants": [
            {
                "name": variant,
                "cohorts": size,
                "successes": successes,
                "success_rate": successes / size,
                "delta_percentage_points": (
                    100 * (successes * control_size - control_successes * size)
                    / (size * control_size)
                ),
            }
            for variant, (size, successes) in sorted(totals.items())
        ],
    })
