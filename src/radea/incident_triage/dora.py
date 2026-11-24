"""Calculate delivery metrics from per-service production deployment events."""

import json
from datetime import datetime
from statistics import median
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Expected timezone-aware timestamps")
    try:
        timestamp = datetime.fromisoformat(
            value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
        )
    except ValueError:
        raise ValueError("Expected timezone-aware ISO 8601 timestamps") from None
    if timestamp.tzinfo is None:
        raise ValueError("Expected timezone-aware timestamps")
    return timestamp


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("Expected nonempty service, deployment and change identifiers")
    return value


def analyse(path: str, limit: int) -> dict:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one deployment event file")
    source = sources[0]
    try:
        document = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid deployment event JSON") from None
    if not isinstance(document, dict) or not isinstance(document.get("window"), dict):
        raise ValueError("Expected a reporting window and deployment records")
    start, end = (_time(document["window"].get(key)) for key in ("start", "end"))
    days = (end - start).total_seconds() / 86400
    if days <= 0:
        raise ValueError("Window end must follow its start")
    records = document.get("deployments")
    if not isinstance(records, list) or len(records) > 20_000:
        raise ValueError("Expected a deployment list with up to 20000 events")
    grouped: dict[str, list[tuple]] = {}
    seen = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("Expected deployment objects")
        service, identity = (_identifier(row.get(key)) for key in ("service", "id"))
        if (service, identity) in seen:
            raise ValueError("Duplicate deployment ID within service")
        seen.add((service, identity))
        deployed = _time(row.get("deployed_at"))
        failed, rework = row.get("failed"), row.get("rework")
        if type(failed) is not bool or type(rework) is not bool:
            raise ValueError("Deployment failure and rework classifications must be booleans")
        recovered = _time(row["recovered_at"]) if row.get("recovered_at") is not None else None
        if recovered is not None and (not failed or recovered < deployed):
            raise ValueError("Recovery must follow a failed deployment")
        changes = row.get("changes", [])
        if not isinstance(changes, list):
            raise ValueError("Deployment changes must be a list")
        timings = {}
        for change in changes:
            if not isinstance(change, dict):
                raise ValueError("Expected change objects")
            change_id = _identifier(change.get("id"))
            committed = _time(change.get("committed_at"))
            if committed > deployed or change_id in timings:
                raise ValueError("Invalid or duplicate committed change in deployment")
            timings[change_id] = (deployed - committed).total_seconds()
        grouped.setdefault(service, []).append(
            (deployed, identity, failed, rework, recovered, timings)
        )

    services = []
    for service, deployments in sorted(grouped.items()):
        count = failures = reworks = unresolved = 0
        lead_times: list[float] = []
        recoveries: list[float] = []
        delivered: set[str] = set()
        for deployed, _, failed, rework, recovered, timings in sorted(deployments):
            in_window = start <= deployed < end
            if in_window:
                count += 1
                failures += failed
                reworks += rework
                if failed:
                    if recovered is not None and recovered <= end:
                        recoveries.append((recovered - deployed).total_seconds())
                    else:
                        unresolved += 1
                else:
                    lead_times.extend(
                        timing for change, timing in timings.items() if change not in delivered
                    )
            if not failed:
                delivered.update(timings)
        services.append(
            {
                "service": service,
                "deployments": count,
                "deployments_per_day": count / days,
                "change_lead_time_median_seconds": median(lead_times) if lead_times else None,
                "change_lead_time_samples": len(lead_times),
                "failed_deployment_recovery_median_seconds": median(recoveries)
                if recoveries
                else None,
                "failed_deployment_recovery_samples": len(recoveries),
                "unrecovered_failures_at_window_end": unresolved,
                "change_fail_rate": failures / count if count else None,
                "deployment_rework_rate": reworks / count if count else None,
            }
        )
    return clean(
        {
            "schema_version": "1.0",
            "command": "dora-report",
            "source": source.meta(),
            "window": {"start": start.isoformat(), "end": end.isoformat()},
            "services": services,
        }
    )
