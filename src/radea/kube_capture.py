"""Read Pod health, associated events and an optional bounded log excerpt."""

import hashlib
import json
import re
import subprocess
from tempfile import TemporaryFile

from radea.core.sanitizer import clean, sanitize
from radea.static_review.kube_health import analyse_snapshot
from radea.static_review.yaml_loader import get

LABEL = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")


def _get(base: list[str], args: list[str], limit: int) -> bytes:
    with TemporaryFile() as output:
        try:
            result = subprocess.run(
                [*base, *args],
                stdout=output,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=20,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError("kubectl unavailable or request timed out") from None
        if result.returncode != 0:
            raise ValueError("kubectl request failed")
        output.seek(0)
        contents = output.read(limit + 1)
    if len(contents) > limit:
        raise ValueError("kubectl response exceeded RADEA_MAX_INPUT_BYTES")
    return contents


def capture(
    kubeconfig: str,
    context: str,
    namespace: str,
    pod: str,
    container: str | None,
    previous: bool,
    limit: int,
) -> dict:
    if not context.strip() or not all(LABEL.fullmatch(x) for x in (namespace, pod)):
        raise ValueError("Specify a concrete Kubernetes context, namespace and Pod")
    if (previous and container is None) or (
        container is not None and not LABEL.fullmatch(container)
    ):
        raise ValueError("Provide a valid container when requesting logs")
    base = [
        "kubectl",
        "--kubeconfig",
        kubeconfig,
        "--context",
        context,
        "--namespace",
        namespace,
        "--request-timeout=12s",
    ]
    raw = _get(base, ["get", "pod", pod, "-o", "json"], limit)
    snapshot = json.loads(raw)
    uid = get(snapshot, "metadata", "uid")
    if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", uid):
        raise ValueError("Pod snapshot has an invalid UID")
    if (
        get(snapshot, "kind") != "Pod"
        or get(snapshot, "metadata", "name") != pod
        or get(snapshot, "metadata", "namespace") != namespace
    ):
        raise ValueError("Pod snapshot does not match the requested resource")
    report = analyse_snapshot(snapshot, {"sha256": hashlib.sha256(raw).hexdigest()})
    warnings = []
    events = []
    try:
        response = json.loads(
            _get(
                base,
                ["get", "events", "--field-selector", f"involvedObject.uid={uid}", "-o", "json"],
                limit,
            )
        )
        items = get(response, "items")
        if not isinstance(items, list):
            raise ValueError("Invalid event list")
        for item in items[-50:]:
            if get(item, "involvedObject", "uid") != uid:
                continue
            events.append(
                {
                    "type": get(item, "type"),
                    "reason": get(item, "reason"),
                    "count": get(item, "count"),
                    "timestamp": get(item, "lastTimestamp") or get(item, "eventTime"),
                }
            )
    except (ValueError, RecursionError):
        warnings.append("events_unavailable")
    logs = None
    if container is not None:
        flags = ["logs", pod, "--container", container, "--tail=50", "--limit-bytes=8192"]
        if previous:
            flags.append("--previous")
        try:
            body = _get(base, flags, min(8192, limit)).decode("utf-8", errors="replace")
            current = json.loads(_get(base, ["get", "pod", pod, "-o", "json"], limit))
            if get(current, "metadata", "uid") != uid:
                raise ValueError("Pod identity changed during log capture")
            logs = {"container": container, "previous": previous, "excerpt": sanitize(body).text}
        except (ValueError, RecursionError):
            warnings.append("logs_unavailable")
    return clean(
        {**report, "command": "k8s-capture", "events": events, "logs": logs, "warnings": warnings}
    )
