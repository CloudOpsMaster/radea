#!/usr/bin/env python3
"""Namespaced example controller for the RADEA Message CRD."""

import argparse
import ipaddress
import json
import os
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory

RESOURCE = "messages.lab.radea.dev"


def error_kind(error: Exception) -> str:
    if isinstance(error, subprocess.CalledProcessError) and isinstance(error.stderr, str):
        for label in ("Forbidden", "Unauthorized", "Conflict", "connection refused"):
            if label.lower() in error.stderr.lower():
                return label
    return type(error).__name__


def in_cluster_config(path: Path) -> None:
    address = ipaddress.ip_address(os.environ["KUBERNETES_SERVICE_HOST"])
    host = f"[{address}]" if address.version == 6 else str(address)
    port = int(os.environ.get("KUBERNETES_SERVICE_PORT", "443"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid Kubernetes service port")
    credentials = "/var/run/secrets/kubernetes.io/serviceaccount"
    path.write_text(json.dumps({
        "apiVersion": "v1", "kind": "Config", "current-context": "pod",
        "clusters": [{
            "name": "api", "cluster": {
                "server": f"https://{host}:{port}",
                "certificate-authority": f"{credentials}/ca.crt",
            },
        }],
        "contexts": [{"name": "pod", "context": {"cluster": "api", "user": "controller"}}],
        "users": [{"name": "controller", "user": {"tokenFile": f"{credentials}/token"}}],
    }), encoding="utf-8")


class Controller:
    def __init__(self, kubeconfig: Path, context: str, namespace: str) -> None:
        self.namespace = namespace
        self.command = [
            "kubectl", "--kubeconfig", str(kubeconfig), "--context", context,
            "--namespace",
            namespace,
            "--request-timeout=10s",
        ]

    def kubectl(self, *args: str, document: dict | None = None) -> str:
        return subprocess.run(
            [*self.command, *args],
            input=json.dumps(document) if document is not None else None,
            stdin=subprocess.DEVNULL if document is None else None,
            capture_output=True,
            check=True,
            text=True,
            timeout=15,
        ).stdout

    def reconcile(self, resource: dict) -> None:
        meta = resource["metadata"]
        if meta.get("deletionTimestamp"):
            return
        child_name = f"message-{meta['uid']}"
        text = resource["spec"]["text"]
        owner = {
            "apiVersion": resource["apiVersion"],
            "kind": resource["kind"],
            "name": meta["name"],
            "uid": meta["uid"],
            "controller": True,
        }
        raw = self.kubectl("get", "configmap", child_name, "--ignore-not-found", "-o", "json")
        if not raw:
            child = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {
                    "name": child_name,
                    "namespace": self.namespace,
                    "ownerReferences": [owner],
                },
                "data": {"text": text},
            }
            self.kubectl("create", "-f", "-", document=child)
        else:
            child = json.loads(raw)
            owners = child["metadata"].get("ownerReferences") or []
            if not any(
                ref.get("uid") == meta["uid"] and ref.get("controller") is True for ref in owners
            ):
                raise ValueError("ConfigMap name is already held by a different owner")
            data = child.get("data") or {}
            if data.get("text") != text:
                child["data"] = {**data, "text": text}
                self.kubectl("replace", "-f", "-", document=child)

        desired_status = {
            "observedGeneration": meta["generation"],
            "configMapName": child_name,
        }
        if resource.get("status") != desired_status:
            patch = {
                "metadata": {"resourceVersion": meta["resourceVersion"]},
                "status": desired_status,
            }
            self.kubectl(
                "patch",
                RESOURCE,
                meta["name"],
                "--subresource=status",
                "--type=merge",
                "--patch",
                json.dumps(patch),
            )

    def sync(self) -> int:
        resources = json.loads(self.kubectl("get", RESOURCE, "-o", "json"))
        failures = 0
        for resource in resources["items"]:
            try:
                self.reconcile(resource)
            except (ValueError, KeyError, subprocess.SubprocessError) as error:
                # Do not echo request payloads or API response bodies.
                print(f"Reconcile failed ({error_kind(error)})", flush=True)
                failures += 1
        return failures


def run(controller: Controller, once: bool) -> int:
    while True:
        try:
            failures = controller.sync()
        except (ValueError, KeyError, subprocess.SubprocessError) as error:
            print(f"List failed ({error_kind(error)})", flush=True)
            failures = 1
        if once:
            return int(bool(failures))
        time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument("--context")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if (args.kubeconfig is None) != (args.context is None):
        parser.error("--kubeconfig and --context must be supplied together")
    if args.kubeconfig is None and (
        not os.environ.get("KUBERNETES_SERVICE_HOST") or os.environ.get("KUBECONFIG")
    ):
        parser.error("Supply a kubeconfig and context, or run with in-cluster credentials")
    if args.kubeconfig is not None:
        return run(Controller(args.kubeconfig, args.context, args.namespace), args.once)
    with TemporaryDirectory(prefix="radea-message-", dir="/tmp") as work:
        kubeconfig = Path(work) / "config.json"
        in_cluster_config(kubeconfig)
        controller = Controller(kubeconfig, "pod", args.namespace)
        controller.command.append(f"--cache-dir={work}/cache")
        return run(controller, args.once)


if __name__ == "__main__":
    raise SystemExit(main())
