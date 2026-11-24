"""Manage namespaced preview environments with an explicit Kubernetes target."""

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any

from radea.static_review.yaml_loader import get

PROJECT = re.compile(r"[a-z][a-z0-9-]{0,29}\Z")
IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*(?:@sha256:[0-9a-f]{64})?\Z")
HEALTH = re.compile(r"/[a-zA-Z0-9._/-]{0,127}\Z")


def identity(project: str, pr: int) -> tuple[str, dict[str, str]]:
    if not PROJECT.fullmatch(project) or project.endswith("-") or not 1 <= pr <= 2**31 - 1:
        raise ValueError("Expected a lowercase project label and a positive PR number")
    return f"radea-{project}-pr-{pr}", {
        "radea.dev/managed-preview": "true",
        "radea.dev/preview-project": project,
        "radea.dev/preview-pr": str(pr),
    }


def _kubectl(base: list[str], *arguments: str, payload: dict | None = None) -> bytes:
    try:
        result = subprocess.run(
            [*base, *arguments],
            input=json.dumps(payload).encode() if payload is not None else b"",
            capture_output=True,
            check=True,
            timeout=100,
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError(f"Kubernetes preview request failed ({arguments[0]})") from None
    return result.stdout


def _namespace(base: list[str], name: str, labels: dict[str, str]) -> dict | None:
    response = _kubectl(base, "get", "namespace", name, "--ignore-not-found", "-o", "json")
    if not response.strip():
        return None
    document = json.loads(response)
    metadata = get(document, "metadata")
    if not isinstance(metadata, dict) or metadata.get("name") != name:
        raise ValueError("Unexpected namespace identity")
    if any(get(metadata, "labels", key) != expected for key, expected in labels.items()):
        raise ValueError("Namespace is outside the selected RADEA preview")
    return metadata


def _target(kubeconfig: str, context: str) -> list[str]:
    if not context.strip():
        raise ValueError("Specify a concrete Kubernetes context")
    return ["kubectl", "--kubeconfig", kubeconfig, "--context", context]


def manifests(namespace: str, image: str, port: int, health: str, command: tuple[str, ...]) -> dict:
    if (
        len(image) > 256
        or not IMAGE.fullmatch(image)
        or not HEALTH.fullmatch(health)
        or not 1 <= port <= 65535
    ):
        raise ValueError("Specify a local health path and a valid container image reference")
    if len(command) > 32 or any(len(argument) > 512 or "\0" in argument for argument in command):
        raise ValueError("Container command exceeds argument bounds")
    labels = {"app.kubernetes.io/name": "preview"}
    metadata = {"name": "app", "namespace": namespace}
    probe = {"httpGet": {"path": health, "port": "http"}}
    container: dict[str, Any] = {
        "name": "app",
        "image": image,
        "ports": [{"name": "http", "containerPort": port}],
        "readinessProbe": probe,
        "livenessProbe": probe,
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "capabilities": {"drop": ["ALL"]},
        },
        "resources": {
            "requests": {"cpu": "25m", "memory": "32Mi"},
            "limits": {"cpu": "500m", "memory": "128Mi"},
        },
    }
    if command:
        container["command"] = list(command)
    workload = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": metadata,
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [container],
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": metadata,
        "spec": {
            "selector": labels,
            "ports": [{"name": "http", "port": port, "targetPort": "http"}],
        },
    }
    return {"apiVersion": "v1", "kind": "List", "items": [workload, service]}


def up(
    project: str,
    pr: int,
    kubeconfig: str,
    context: str,
    image: str,
    port: int,
    health: str,
    command: tuple[str, ...],
) -> dict:
    name, labels = identity(project, pr)
    bundle = manifests(name, image, port, health, command)
    target = _target(kubeconfig, context)
    metadata = _namespace(target, name, labels)
    if metadata is None:
        _kubectl(
            target,
            "create",
            "-f",
            "-",
            payload={
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": name, "labels": labels},
            },
        )
    elif metadata.get("deletionTimestamp"):
        raise ValueError("Preview namespace is still terminating")
    scoped = [*target, "--namespace", name]
    _kubectl(
        scoped, "apply", "--server-side", "--field-manager=radea-preview", "-f", "-", payload=bundle
    )
    _kubectl(scoped, "rollout", "status", "deployment/app", "--timeout=90s")
    return {"namespace": name, "status": "ready", "service": f"http://app.{name}:{port}"}


def down(project: str, pr: int, kubeconfig: str, context: str) -> dict:
    name, labels = identity(project, pr)
    target = _target(kubeconfig, context)
    metadata = _namespace(target, name, labels)
    if metadata is None:
        return {"namespace": name, "status": "absent"}
    if not metadata.get("deletionTimestamp"):
        _delete(target, name, _preconditions(metadata))
    return {"namespace": name, "status": "deletion_requested"}


def _preconditions(metadata: dict) -> dict:
    conditions = {key: metadata.get(key) for key in ("uid", "resourceVersion")}
    if not all(isinstance(value, str) and value for value in conditions.values()):
        raise ValueError("Cannot verify preview deletion preconditions")
    return conditions


def _delete(target: list[str], name: str, conditions: dict) -> None:
    _kubectl(
        target,
        "delete",
        "--raw",
        f"/api/v1/namespaces/{name}",
        "-f",
        "-",
        payload={"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": conditions},
    )


def sweep(
    project: str,
    kubeconfig: str,
    context: str,
    older_than: int,
    apply: bool,
    maximum: int,
) -> dict:
    _, labels = identity(project, 1)
    if not 1 <= older_than <= 31_536_000 or not 1 <= maximum <= 100:
        raise ValueError("Invalid preview cleanup limits")
    target = _target(kubeconfig, context)
    selector = ",".join(
        f"{key}={value}" for key, value in labels.items() if key != "radea.dev/preview-pr"
    )
    response = json.loads(_kubectl(target, "get", "namespaces", "-l", selector, "-o", "json"))
    items = get(response, "items")
    if not isinstance(items, list):
        raise ValueError("Expected a namespace list from Kubernetes")
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than)
    candidates = {}
    for item in items:
        metadata = get(item, "metadata")
        if not isinstance(metadata, dict) or metadata.get("deletionTimestamp"):
            continue
        pr = get(metadata, "labels", "radea.dev/preview-pr")
        if not isinstance(pr, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", pr):
            continue
        if int(pr) > 2**31 - 1:
            continue
        name, expected = identity(project, int(pr))
        if metadata.get("name") != name or any(
            get(metadata, "labels", key) != value for key, value in expected.items()
        ):
            continue
        timestamp = metadata.get("creationTimestamp")
        if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
            raise ValueError("Missing Kubernetes creation timestamp on a managed preview")
        created = datetime.fromisoformat(timestamp[:-1] + "+00:00")
        if created.tzinfo is None:
            raise ValueError("Invalid Kubernetes creation timestamp on a managed preview")
        if created <= cutoff:
            if name in candidates:
                raise ValueError("Duplicate preview namespace in snapshot")
            candidates[name] = _preconditions(metadata)
    if apply and len(candidates) > maximum:
        raise ValueError("Expired preview count exceeds the deletion limit")
    failed = []
    requested = []
    if apply:
        for name, conditions in sorted(candidates.items()):
            try:
                _delete(target, name, conditions)
            except ValueError:
                failed.append(name)
            else:
                requested.append(name)
    return {
        "project": project,
        "mode": "apply" if apply else "plan",
        "older_than_seconds": older_than,
        "candidates": sorted(candidates),
        "deletion_requested": requested,
        "failed": failed,
    }


def event_decision(event: Any, repository: str) -> tuple[str, int | None]:
    """Map trusted GitHub event metadata to a local preview action."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected a GitHub repository in OWNER/REPO form")
    if not isinstance(event, dict) or get(event, "repository", "full_name") != repository:
        raise ValueError("Pull request event does not match the configured repository")
    action = event.get("action")
    if action not in ("opened", "synchronize", "reopened", "closed"):
        return "ignored", None
    if get(event, "pull_request", "base", "repo", "full_name") != repository:
        raise ValueError("Pull request base repository does not match")
    if get(event, "pull_request", "head", "repo", "full_name") != repository:
        return "ignored", None
    number = event.get("number")
    if (
        type(number) is not int
        or not 1 <= number <= 2**31 - 1
        or get(event, "pull_request", "number") != number
    ):
        raise ValueError("Invalid or inconsistent pull request number")
    expected_state = "closed" if action == "closed" else "open"
    if get(event, "pull_request", "state") != expected_state:
        raise ValueError("Pull request state does not match the lifecycle action")
    return ("down" if action == "closed" else "up"), number
