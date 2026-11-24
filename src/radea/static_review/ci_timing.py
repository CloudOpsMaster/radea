"""Summarize pipeline feedback time from captured run and job timings."""

import json
from statistics import median
from typing import Any

from radea.static_review.files import collect


def _seconds(value: Any, ceiling: float, field: str) -> float:
    if type(value) not in (int, float) or not 0 <= value <= ceiling:
        raise ValueError(f"Invalid {field} within the run")
    return float(value)


def _summary(runs: Any) -> dict:
    if not isinstance(runs, list) or not 1 <= len(runs) <= 10_000:
        raise ValueError("Each cohort requires 1–10000 CI runs")
    elapsed = []
    signals = []
    diagnoses = []
    hits = misses = 0
    peak = []
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("jobs"), list):
            raise ValueError("Each CI run requires a jobs list")
        duration = _seconds(run.get("duration_seconds"), 31_536_000, "duration")
        elapsed.append(duration)
        diagnosed = run.get("diagnosed_seconds")
        if diagnosed is not None:
            diagnoses.append(_seconds(diagnosed, 31_536_000, "diagnosis time"))
        failures = []
        events: list[tuple[float, int]] = []
        for job in run["jobs"]:
            if not isinstance(job, dict):
                raise ValueError("Expected CI job records")
            start = _seconds(job.get("started_seconds"), duration, "job start")
            end = _seconds(job.get("finished_seconds"), duration, "job finish")
            outcome, cache = job.get("outcome"), job.get("cache", "unknown")
            if end < start or outcome not in ("pass", "fail", "skip", "cancel"):
                raise ValueError("Invalid CI job interval or outcome")
            if cache not in ("hit", "miss", "unknown"):
                raise ValueError("Invalid CI job cache outcome")
            hits += cache == "hit"
            misses += cache == "miss"
            if outcome == "fail":
                failures.append(end)
            if start < end and outcome != "skip":
                events.extend(((start, 1), (end, -1)))
        if failures:
            signals.append(min(failures))
        active = highest = 0
        for _, delta in sorted(events):
            active += delta
            highest = max(highest, active)
        peak.append(highest)
    return {
        "runs": len(runs),
        "wall_median_seconds": median(elapsed),
        "first_failure_median_seconds": median(signals) if signals else None,
        "first_failure_samples": len(signals),
        "diagnosis_median_seconds": median(diagnoses) if diagnoses else None,
        "diagnosis_samples": len(diagnoses),
        "peak_parallel_jobs_median": median(peak),
        "observed_cache_hits": hits,
        "observed_cache_misses": misses,
        "observed_cache_hit_rate": hits / (hits + misses) if hits + misses else None,
    }


def analyse(path: str, limit: int) -> dict:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one CI timing file")
    try:
        data = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid CI timings JSON") from None
    if not isinstance(data, dict):
        raise ValueError("Expected baseline and candidate cohorts")
    baseline, candidate = (_summary(data.get(key)) for key in ("baseline", "candidate"))
    delta = {}
    for key in ("wall_median_seconds", "first_failure_median_seconds", "diagnosis_median_seconds"):
        before, after = baseline[key], candidate[key]
        delta[key] = after - before if before is not None and after is not None else None
    return {
        "schema_version": "1.0",
        "command": "ci-timing",
        "source": sources[0].meta(),
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
    }
