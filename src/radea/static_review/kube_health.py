"""Read a captured Kubernetes Pod or PodList and report structured symptoms."""

import json
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect
from radea.static_review.yaml_loader import get

CHECKS = {
    "CrashLoopBackOff": "Inspect previous container logs and exit status.",
    "ImagePullBackOff": "Confirm the image reference, registry access and pull credentials.",
    "ErrImagePull": "Confirm the image reference, registry access and pull credentials.",
    "CreateContainerConfigError": "Check referenced ConfigMaps and Secrets in the Pod namespace.",
    "OOMKilled": "Compare peak memory against the container memory limit.",
    "Evicted": "Check node pressure and Pod resource requests.",
    "Unschedulable": "Check scheduling events, resource requests, affinity and tolerations.",
    "PodNotReady": "Check readiness probe results and EndpointSlice membership.",
    "PodFailed": "Inspect Pod events and terminated container exit status.",
    "InitContainerFailed": "Inspect the init container's previous logs and exit status.",
}


def _pod_records(snapshot: Any) -> list:
    if isinstance(snapshot, dict) and snapshot.get("kind") == "Pod":
        return [snapshot]
    if isinstance(snapshot, dict) and snapshot.get("kind") in ("List", "PodList"):
        items = snapshot.get("items")
        default_kind = "Pod" if snapshot["kind"] == "PodList" else None
        if isinstance(items, list) and all(
            isinstance(pod, dict) and pod.get("kind", default_kind) == "Pod" for pod in items
        ):
            return items
    raise ValueError("Expected Kubernetes Pod, PodList or List of Pods JSON")


def analyse(path: str, max_bytes: int) -> dict:
    sources, _ = collect([path], max_bytes=max_bytes)
    if len(sources) != 1:
        raise ValueError("Expected one Kubernetes Pod snapshot")
    source = sources[0]
    try:
        snapshot = json.loads(source.text)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError("Invalid Pod snapshot JSON") from None
    return analyse_snapshot(snapshot, source.meta())


def analyse_snapshot(snapshot: Any, source: dict) -> dict:
    pods = _pod_records(snapshot)
    records = []
    warnings = 0
    for pod in pods:
        name = get(pod, "metadata", "name")
        namespace = get(pod, "metadata", "namespace")
        status = get(pod, "status")
        if not isinstance(name, str) or not name:
            raise ValueError("Each Pod must have metadata.name")
        if not isinstance(status, dict):
            status = {}
        phase = status.get("phase")
        conditions = status.get("conditions")
        conditions = conditions if isinstance(conditions, list) else []
        signals = []
        restarts = 0

        def emit(reason: Any, container: str | None = None) -> None:
            if isinstance(reason, str) and reason in CHECKS:
                signals.append({"reason": reason, "container": container, "check": CHECKS[reason]})

        if status.get("reason") == "Evicted":
            emit("Evicted")
        elif phase == "Failed":
            emit("PodFailed")
        for condition in conditions:
            if get(condition, "type") == "PodScheduled" and get(condition, "status") == "False":
                emit(get(condition, "reason"))
            if phase == "Running" and get(condition, "type") == "Ready":
                if get(condition, "status") != "True":
                    emit("PodNotReady")
        for field in ("initContainerStatuses", "containerStatuses"):
            containers = status.get(field)
            if not isinstance(containers, list):
                continue
            for container in containers:
                label = get(container, "name")
                count = get(container, "restartCount")
                if type(count) is int and count >= 0:
                    restarts += count
                if not isinstance(label, str):
                    continue
                emit(get(container, "state", "waiting", "reason"), label)
                terminated = get(container, "state", "terminated")
                if (
                    get(terminated, "reason") == "OOMKilled"
                    or get(container, "lastState", "terminated", "reason") == "OOMKilled"
                ):
                    emit("OOMKilled", label)
                elif field == "initContainerStatuses":
                    code = get(terminated, "exitCode")
                    if type(code) is int and code != 0:
                        emit("InitContainerFailed", label)
        warnings += len(signals)
        records.append(
            {
                "name": name,
                "namespace": namespace if isinstance(namespace, str) else "",
                "phase": phase
                if phase in ("Pending", "Running", "Succeeded", "Failed", "Unknown")
                else "Unknown",
                "restarts": restarts,
                "signals": signals,
            }
        )
    return clean(
        {
            "schema_version": "1.0",
            "command": "k8s-health",
            "source": source,
            "summary": {"pods": len(records), "signals": warnings},
            "pods": sorted(records, key=lambda item: (item["namespace"], item["name"])),
        }
    )
