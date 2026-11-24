"""Gate an HTTP smoke suite on the rollout of a selected Kubernetes Deployment."""

import json

from radea.core.sanitizer import clean
from radea.kube_capture import LABEL, _get
from radea.migration import _path
from radea.migration_parity import _canonical_json, _read
from radea.static_review.files import collect


def check(
    spec: str, origin: str, kubeconfig: str, context: str, namespace: str,
    deployment: str, limit: int,
) -> dict:
    if not context.strip() or not all(LABEL.fullmatch(x) for x in (namespace, deployment)):
        raise ValueError("Specify a concrete Kubernetes context, namespace and Deployment")
    sources, _ = collect([spec], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one smoke test specification")
    source = sources[0]
    try:
        cases = json.loads(source.text)
        if not isinstance(cases, list) or not 1 <= len(cases) <= 10:
            raise ValueError
        requests = []
        for case in cases:
            if not isinstance(case, dict) or case.keys() - {"path", "status", "json"}:
                raise ValueError
            path, status = case.get("path"), case.get("status")
            if not isinstance(path, str) or type(status) is not int or not 200 <= status <= 599:
                raise ValueError
            _path(path)  # Validate the path while preserving a trailing slash.
            expected = (
                json.dumps(case["json"], sort_keys=True, allow_nan=False)
                if "json" in case else None
            )
            requests.append((path, status, expected))
    except (ValueError, RecursionError):
        raise ValueError(
            "Expected 1–10 smoke cases with a normalized path and HTTP status"
        ) from None

    base = [
        "kubectl", "--kubeconfig", kubeconfig, "--context", context, "--namespace", namespace,
        "--request-timeout=15s",
    ]
    try:
        _get(base, ["rollout", "status", f"deployment/{deployment}", "--timeout=12s"], limit)
    except ValueError:
        raise ValueError("Could not confirm Deployment rollout readiness") from None

    results = []
    for index, (path, status, expected) in enumerate(requests, 1):
        actual = None
        differences = []
        try:
            actual, media, body = _read(origin, path, limit)
        except ValueError:
            differences.append("response_unavailable")
        else:
            if actual != status:
                differences.append("status")
            if expected is not None:
                try:
                    matches = media == "application/json" and _canonical_json(body) == expected
                except ValueError:
                    matches = False
                if not matches:
                    differences.append("json")
        results.append({
            "case": index, "expected_status": status, "actual_status": actual,
            "differences": differences,
        })
    return clean({
        "schema_version": "1.0", "command": "k8s-smoke", "source": source.meta(),
        "namespace": namespace, "deployment": deployment,
        "passed": all(not item["differences"] for item in results), "cases": results,
    })
