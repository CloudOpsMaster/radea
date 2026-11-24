"""Score current readings against supplied rolling metric and cost baselines."""

import json
import math
import re
from statistics import median

from radea.prometheus import query
from radea.static_review.files import collect
from radea.static_review.yaml_loader import get

METRIC = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


def _number(value) -> float:
    if type(value) not in (int, float) or abs(value) > 1e150 or not math.isfinite(value):
        raise ValueError("Readings must be finite numbers within supported magnitude")
    return float(value)


def _prometheus_series(
    endpoint: str, expression: str, window: int, step: int, now: int
) -> dict:
    start = now - window * step
    data = query(endpoint, "query_range", {
        "query": expression, "start": float(start), "end": float(now),
        "step": f"{step}s", "timeout": "5s",
    })
    rows = get(data, "result")
    if get(data, "resultType") != "matrix" or not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("Each Prometheus query must return one series")
    samples = get(rows[0], "values")
    if not isinstance(samples, list) or len(samples) != window + 1:
        raise ValueError("Prometheus series has missing or extra samples")
    values = []
    for index, sample in enumerate(samples):
        if (
            not isinstance(sample, list)
            or len(sample) != 2
            or type(sample[0]) not in (int, float)
            or sample[0] != start + index * step
            or not isinstance(sample[1], str)
        ):
            raise ValueError("Invalid or misaligned Prometheus sample")
        try:
            values.append(_number(float(sample[1])))
        except ValueError:
            raise ValueError("Invalid Prometheus sample value") from None
    return {"history": values[:-1], "current": values[-1]}


def analyse(
    path: str, max_bytes: int, window: int, threshold: float, relative: float,
    *, prometheus: str | None = None, step: int = 60, now: int = 0,
) -> dict:
    sources, _ = collect([path], max_bytes=max_bytes)
    if len(sources) != 1:
        raise ValueError("Expected one metric series file")
    source = sources[0]
    try:
        document = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid metric series JSON") from None
    if not math.isfinite(threshold) or not math.isfinite(relative):
        raise ValueError("Thresholds must be finite")
    if prometheus is None:
        series = get(document, "series")
        if not isinstance(series, dict) or not 1 <= len(series) <= 100:
            raise ValueError("Expected 1–100 named metric series")
    else:
        expressions = get(document, "queries")
        if not isinstance(expressions, dict) or not 1 <= len(expressions) <= 10:
            raise ValueError("Expected 1–10 named Prometheus queries")
        if window > 1000:
            raise ValueError("Prometheus mode supports up to 1000 historical readings")
        for name, expression in expressions.items():
            if (
                not METRIC.fullmatch(name)
                or not isinstance(expression, str)
                or not expression.strip()
                or len(expression) > 1024
            ):
                raise ValueError("Invalid Prometheus query configuration")
        now -= now % step
        series = {
            name: _prometheus_series(prometheus, expression, window, step, now)
            for name, expression in sorted(expressions.items())
        }

    results = []
    for name, entry in sorted(series.items()):
        if not METRIC.fullmatch(name) or not isinstance(entry, dict):
            raise ValueError("Invalid metric series")
        history = entry.get("history")
        if not isinstance(history, list) or len(history) < window:
            raise ValueError(f"Series {name} needs at least {window} historical readings")
        readings = [_number(value) for value in history[-window:]]
        current = _number(entry.get("current"))
        center = median(readings)
        scale = 1.4826 * median(abs(value - center) for value in readings)
        delta = current - center
        boundary = max(threshold * scale, relative * abs(center))
        results.append(
            {
                "metric": name,
                "window": window,
                "baseline_median": center,
                "baseline_scaled_mad": scale,
                "current": current,
                "delta": delta,
                "threshold_delta": boundary,
                "anomaly": abs(delta) > boundary,
            }
        )
    return {
        "schema_version": "1.0",
        "command": "metric-anomalies",
        "source": source.meta(),
        "metrics": results,
        **({"sampled_at": now, "step_seconds": step} if prometheus is not None else {}),
    }


def transitions(metrics: list[dict], active: set[str]) -> list[dict]:
    """Record only newly opened or recovered anomalies; absent metrics keep their state."""
    events = []
    for item in metrics:
        metric, is_anomalous = item["metric"], item["anomaly"]
        if is_anomalous and metric not in active:
            active.add(metric)
            events.append({**item, "event": "opened"})
        elif not is_anomalous and metric in active:
            active.remove(metric)
            events.append({**item, "event": "recovered"})
    return events
