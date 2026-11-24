"""Prepare a guarded, restricted ephemeral probe for a captured Pod."""

import json
import re

from radea.kube_capture import LABEL
from radea.static_review.files import collect
from radea.static_review.yaml_loader import get

IMAGE = re.compile(r"[a-z0-9][a-z0-9.:-]*(?:/[a-z0-9][a-z0-9._-]*)+@sha256:[a-f0-9]{64}\Z")
PROBES = {
    "identity": ["id"],
    "resolver": ["cat", "/etc/resolv.conf"],
    "interfaces": ["ip", "addr", "show"],
}


def plan(snapshot: str, image: str, probe: str, limit: int) -> list[dict]:
    if not IMAGE.fullmatch(image):
        raise ValueError("Provide a fully qualified debug image pinned by SHA-256")
    if probe not in PROBES:
        raise ValueError("Unknown restricted debug probe")
    sources, _ = collect([snapshot], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one Pod snapshot")
    try:
        document = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid Pod snapshot JSON") from None
    metadata = get(document, "metadata")
    if (
        get(document, "kind") != "Pod" or get(document, "apiVersion") != "v1"
        or not isinstance(metadata, dict) or metadata.get("deletionTimestamp")
        or any(
            not isinstance(metadata.get(key), str) or not LABEL.fullmatch(metadata[key])
            for key in ("name", "namespace", "uid")
        )
    ):
        raise ValueError("Expected an active named Pod snapshot")
    version = metadata.get("resourceVersion")
    if not isinstance(version, str) or not version or len(version) > 128:
        raise ValueError("Pod snapshot is missing a resourceVersion")
    if not isinstance(get(document, "spec", "containers"), list):
        raise ValueError("Pod snapshot is missing its container list")
    if any(get(document, "spec", key) is True for key in ("hostNetwork", "hostPID", "hostIPC")):
        raise ValueError("Restricted probe requires a Pod without host namespace sharing")
    name = f"radea-{probe}"
    for field in ("containers", "initContainers", "ephemeralContainers"):
        containers = get(document, "spec", field)
        if containers is not None and not isinstance(containers, list):
            raise ValueError("Invalid Pod container list")
        if any(get(container, "name") == name for container in containers or []):
            raise ValueError("Pod already has a container for this probe")
    existing = get(document, "spec", "ephemeralContainers")
    container = {
        "name": name,
        "image": image,
        "command": PROBES[probe],
        "securityContext": {
            "runAsNonRoot": True, "runAsUser": 65534, "runAsGroup": 65534,
            "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"},
        },
    }
    return [
        {"op": "test", "path": "/metadata/uid", "value": metadata["uid"]},
        {"op": "test", "path": "/metadata/resourceVersion", "value": version},
        {
            "op": "add",
            "path": "/spec/ephemeralContainers/-" if existing is not None
            else "/spec/ephemeralContainers",
            "value": container if existing is not None else [container],
        },
    ]
