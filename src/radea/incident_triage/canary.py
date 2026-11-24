"""Evaluate candidate health measurements for a progressive-delivery decision."""

import json
import math
from typing import Any

from radea.static_review.files import collect


def decide(
    path: str, limit: int, minimum: int, success_floor: float, latency_ceiling: float
) -> dict:
    if not math.isfinite(success_floor) or not math.isfinite(latency_ceiling):
        raise ValueError("Canary thresholds must be finite")
    files, _ = collect([path], max_bytes=limit)
    if len(files) != 1:
        raise ValueError("Expected one canary measurement file")
    source = files[0]
    try:
        document = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid canary measurement JSON") from None
    requests = document.get("requests") if isinstance(document, dict) else None
    if not isinstance(requests, list) or len(requests) > 100_000:
        raise ValueError("Expected up to 100000 candidate requests")
    successful_latencies: list[float] = []
    for row in requests:
        success = row.get("ok") if isinstance(row, dict) else None
        if type(success) is not bool:
            raise ValueError("Every candidate request requires a boolean ok field")
        if success:
            successful_latencies.append(_latency(row.get("latency_ms")))
    count = len(requests)
    rate = len(successful_latencies) / count if count else None
    successful_latencies.sort()
    rank = math.ceil(0.95 * len(successful_latencies))
    latency = successful_latencies[rank - 1] if rank else None
    reasons = []
    if count < minimum:
        decision = "hold"
        reasons.append("insufficient_samples")
    else:
        if rate is None or rate < success_floor:
            reasons.append("success_rate")
        if latency is None or latency > latency_ceiling:
            reasons.append("p95_success_latency")
        decision = "rollback" if reasons else "promote"
    return {
        "schema_version": "1.0",
        "command": "canary-gate",
        "source": source.meta(),
        "decision": decision,
        "reasons": reasons,
        "requests": count,
        "successful_requests": len(successful_latencies),
        "success_rate": rate,
        "p95_success_latency_ms": latency,
        "thresholds": {
            "min_requests": minimum,
            "min_success_rate": success_floor,
            "max_p95_ms": latency_ceiling,
        },
    }


def _latency(value: Any) -> float:
    if type(value) not in (int, float) or not 0 <= value <= 86_400_000:
        raise ValueError("Successful requests require a valid latency in milliseconds")
    return float(value)
