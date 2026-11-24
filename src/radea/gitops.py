"""Reconcile a bounded, namespaced bundle from a committed local Git revision."""

import json
import os
import re
import subprocess
from pathlib import PurePosixPath
from typing import Any

from radea.static_review.yaml_loader import load_all

NAMESPACE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
NAME = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?\Z")


def _run(args: list[str], *, payload: bytes | None = None, env=None) -> bytes:
    try:
        return subprocess.run(
            args,
            input=payload,
            capture_output=True,
            check=True,
            timeout=30,
            env=env,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError(f"{args[0]} operation failed during GitOps sync") from None


def _bundle(raw: bytes, namespace: str, *, allow_deployments: bool = False) -> list[dict]:
    documents = [doc for doc in load_all(raw.decode(), strict=True) if doc is not None]
    if not 1 <= len(documents) <= 100:
        raise ValueError("Expected 1–100 committed Kubernetes resources")
    identities = set()
    supported = {("v1", "ConfigMap"), ("v1", "Service")}
    if allow_deployments:
        supported.add(("apps/v1", "Deployment"))
    for doc in documents:
        meta = doc.get("metadata") if isinstance(doc, dict) else None
        if not isinstance(meta, dict) or meta.get("namespace") != namespace:
            raise ValueError("Every resource must explicitly declare the target namespace")
        name = meta.get("name")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError("Every resource requires a valid Kubernetes name")
        if set(meta) - {"name", "namespace", "labels", "annotations"}:
            raise ValueError("GitOps bundle contains unsupported resource metadata")
        kind = doc.get("kind")
        version = doc.get("apiVersion")
        if not isinstance(version, str) or not isinstance(kind, str) or (
            version, kind
        ) not in supported:
            raise ValueError("Unsupported GitOps resource kind for the selected options")
        if kind == "Service":
            spec = doc.get("spec")
            if (
                not isinstance(spec, dict)
                or spec.get("type", "ClusterIP") != "ClusterIP"
                or not isinstance(spec.get("selector"), dict)
                or not spec["selector"]
                or "externalIPs" in spec
            ):
                raise ValueError("Services must use ClusterIP, a selector and no external IPs")
        identity = kind, name
        if identity in identities:
            raise ValueError("Duplicate resource in GitOps bundle")
        identities.add(identity)
    return documents


def sync(
    repo: str,
    ref: str,
    manifest: str,
    kubeconfig: str,
    context: str,
    namespace: str,
    limit: int,
    *,
    force_conflicts: bool = False,
    remote: str | None = None,
    applyset: str | None = None,
    allow_deployments: bool = False,
) -> dict[str, Any]:
    if not NAMESPACE.fullmatch(namespace) or not context.strip():
        raise ValueError("GitOps requires a concrete namespace and context")
    if applyset is not None and (not NAMESPACE.fullmatch(applyset) or force_conflicts):
        raise ValueError("ApplySet requires a DNS label and cannot use --force-conflicts")
    path = PurePosixPath(manifest)
    if not manifest or path.is_absolute() or ".." in path.parts or ":" in manifest:
        raise ValueError("Manifest must be a repository-relative path")
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git = ["git", "-C", repo]
    if remote is not None:
        env["GIT_TERMINAL_PROMPT"] = "0"
        if not NAMESPACE.fullmatch(remote) or ref == "HEAD" or not ref.startswith("refs/heads/"):
            raise ValueError("Remote sync requires a configured remote and a refs/heads/ branch")
        _run([*git, "remote", "get-url", remote], env=env)
        _run([*git, "check-ref-format", ref], env=env)
        local_ref = f"refs/radea/gitops/{remote}/{ref.removeprefix('refs/heads/')}"
        _run(
            [
                *git,
                "-c",
                "protocol.ext.allow=never",
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                "--no-write-fetch-head",
                remote,
                f"{ref}:{local_ref}",
            ],
            env=env,
        )
        ref = local_ref
    commit = (
        _run([*git, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], env=env)
        .decode()
        .strip()
    )
    if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", commit):
        raise ValueError("Git returned an invalid commit ID")
    blob = f"{commit}:{path.as_posix()}"
    if _run([*git, "cat-file", "-t", blob], env=env).strip() != b"blob":
        raise ValueError("Manifest path must refer to a Git blob")
    if int(_run([*git, "cat-file", "-s", blob], env=env)) > limit:
        raise ValueError("Committed manifest exceeds RADEA_MAX_INPUT_BYTES")
    docs = _bundle(
        _run([*git, "cat-file", "blob", blob], env=env), namespace,
        allow_deployments=allow_deployments,
    )
    try:
        payload = json.dumps(
            {"apiVersion": "v1", "kind": "List", "items": docs}, allow_nan=False
        ).encode()
    except (ValueError, TypeError, RecursionError):
        raise ValueError("GitOps resources must be JSON-compatible Kubernetes objects") from None
    kubectl = [
        "kubectl",
        "--kubeconfig",
        kubeconfig,
        "--context",
        context,
        "--namespace",
        namespace,
        "--request-timeout=20s",
        "apply",
        "--field-manager=radea-gitops",
        "-f",
        "-",
    ]
    operation_env = None
    if applyset is not None:
        if any(doc["kind"] == "ConfigMap" and doc["metadata"]["name"] == applyset for doc in docs):
            raise ValueError("The ApplySet inventory ConfigMap must be separate from the bundle")
        kubectl.extend(("--prune", f"--applyset=configmaps/{applyset}"))
        operation_env = {**os.environ, "KUBECTL_APPLYSET": "true"}
    else:
        kubectl.append("--server-side")
    if force_conflicts:
        kubectl.append("--force-conflicts")
    _run(kubectl, payload=payload, env=operation_env)
    report = {"commit": commit, "resources_applied": len(docs), "namespace": namespace}
    if applyset is not None:
        report["applyset"] = applyset
    return report
