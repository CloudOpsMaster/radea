"""Drive weighted Gateway API rollouts using candidate-scoped Prometheus signals."""

import json
import math
import re
import time
from typing import Any

from radea.preview import _kubectl, _target
from radea.static_review.files import collect
from radea.static_review.yaml_loader import get

API = "gateway.networking.k8s.io/v1"
START = "radea.dev/canary-started"
LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
SIGNALS = ("requests", "success_rate", "p95_ms", "sample_age_seconds")


def _label(value: Any) -> str:
    if not isinstance(value, str) or not LABEL.fullmatch(value):
        raise ValueError("Expected a Kubernetes DNS label")
    return value


def emit_route(
    namespace: str,
    name: str,
    gateway: str,
    stable: str,
    candidate: str,
    port: int,
    weight: int,
    prefix: str,
    gateway_namespace: str | None = None,
    listener: str | None = None,
    hostname: str | None = None,
    shadow_reads: bool = False,
) -> dict:
    namespace, name, gateway, stable, candidate = map(
        _label, (namespace, name, gateway, stable, candidate)
    )
    if stable == candidate or not 1 <= port <= 65535 or not 0 <= weight <= 100:
        raise ValueError("Use distinct backends and valid Service port and weight")
    if (
        not re.fullmatch(r"/[A-Za-z0-9._/-]{0,199}", prefix)
        or "//" in prefix
        or any(part in (".", "..") for part in prefix.split("/"))
    ):
        raise ValueError("Expected a normalized HTTP path prefix")
    parent = {"name": gateway}
    if gateway_namespace:
        parent["namespace"] = _label(gateway_namespace)
    if listener:
        parent["sectionName"] = _label(listener)
    hostnames = {}
    if hostname:
        if len(hostname) > 253 or any(not LABEL.fullmatch(label) for label in hostname.split(".")):
            raise ValueError("Expected a lowercase DNS hostname")
        hostnames["hostnames"] = [hostname]
    path = {"type": "PathPrefix", "value": prefix}
    backends = [
        {"name": stable, "port": port, "weight": 100 - weight},
        {"name": candidate, "port": port, "weight": weight},
    ]
    rules = [{"matches": [{"path": path}], "backendRefs": backends}]
    if shadow_reads:
        if weight != 0:
            raise ValueError("Read-only shadow mode requires a zero candidate weight")
        rules.insert(
            0,
            {
                "matches": [{"path": path, "method": method} for method in ("GET", "HEAD")],
                "filters": [
                    {
                        "type": "RequestMirror",
                        "requestMirror": {"backendRef": {"name": candidate, "port": port}},
                    }
                ],
                "backendRefs": [backends[0]],
            },
        )
        rules[1]["backendRefs"] = [backends[0]]
    return {
        "apiVersion": API,
        "kind": "HTTPRoute",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"parentRefs": [parent], "rules": rules, **hostnames},
    }


def load_policy(path: str, limit: int) -> dict:
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one rollout policy file")
    try:
        policy = json.loads(sources[0].text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid rollout policy JSON") from None
    queries = get(policy, "queries")
    if (
        not isinstance(queries, dict)
        or set(queries) != set(SIGNALS)
        or not all(isinstance(q, str) and 1 <= len(q) <= 3000 for q in queries.values())
    ):
        raise ValueError("Policy requires four bounded Prometheus queries")
    assert isinstance(policy, dict)
    for key, low, high in (
        ("min_requests", 1, 1_000_000_000),
        ("min_success_rate", 0, 1),
        ("max_p95_ms", 0, 3_600_000),
        ("window_seconds", 1, 3600),
        ("max_sample_age_seconds", 1, 3600),
    ):
        value = policy.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not low <= value <= high
        ):
            raise ValueError(f"Invalid rollout policy threshold: {key}")
    steps = policy.get("steps", [100])
    if (
        not isinstance(steps, list)
        or not steps
        or any(type(step) is not int or not 1 <= step <= 100 for step in steps)
        or steps != sorted(set(steps))
        or steps[-1] != 100
    ):
        raise ValueError("Policy steps must be increasing integer weights ending in 100")
    return {**policy, "steps": steps}


def _query(endpoint: str, expression: str, now: float) -> float:
    from radea.prometheus import query

    data = query(endpoint, "query", {"query": expression, "time": now, "timeout": "5s"})
    kind, rows = get(data, "resultType"), get(data, "result")
    if kind == "vector" and isinstance(rows, list) and len(rows) == 1:
        rows = get(rows[0], "value")
    elif kind != "scalar":
        raise ValueError("Each query must return a scalar or one series")
    if not isinstance(rows, list) or len(rows) != 2 or not isinstance(rows[1], str):
        raise ValueError("Invalid Prometheus sample")
    result = float(rows[1])
    if not math.isfinite(result):
        raise ValueError("Prometheus returned a nonfinite sample")
    return result


def _route_state(
    document: Any, namespace: str, route_name: str, stable: str, candidate: str, rule_index: int
) -> tuple[dict, list[dict]]:
    meta = get(document, "metadata")
    backends = get(document, "spec", "rules", rule_index, "backendRefs")
    if (
        get(document, "apiVersion") != API
        or get(document, "kind") != "HTTPRoute"
        or not isinstance(meta, dict)
        or meta.get("name") != route_name
        or meta.get("namespace") != namespace
        or not isinstance(meta.get("resourceVersion"), str)
        or not meta["resourceVersion"]
        or not isinstance(backends, list)
        or len(backends) != 2
    ):
        raise ValueError("Expected an identifiable v1 HTTPRoute rule with exactly two backends")
    for ref in backends:
        if (
            not isinstance(ref, dict)
            or ref.get("group", "") != ""
            or ref.get("kind", "Service") != "Service"
            or ref.get("namespace", namespace) != namespace
            or type(ref.get("port")) is not int
            or not 1 <= ref["port"] <= 65535
            or type(ref.get("weight", 1)) is not int
            or ref.get("weight", 1) < 0
        ):
            raise ValueError("Only two same-namespace Service references are supported")
    if sorted(_label(ref.get("name")) for ref in backends) != sorted((stable, candidate)):
        raise ValueError("HTTPRoute backend names do not match the selected stable and candidate")
    return meta, backends


def _ready(document: dict, generation: Any) -> bool:
    parents = get(document, "status", "parents")
    desired = get(document, "spec", "parentRefs")
    namespace = get(document, "metadata", "namespace")
    if (
        type(generation) is not int
        or not isinstance(parents, list)
        or not isinstance(desired, list)
        or not desired
    ):
        return False

    def identity(ref: Any) -> tuple:
        if not isinstance(ref, dict):
            return ()
        return (
            ref.get("group", "gateway.networking.k8s.io"),
            ref.get("kind", "Gateway"),
            ref.get("namespace", namespace),
            ref.get("name"),
            ref.get("sectionName"),
            ref.get("port"),
        )

    active = [identity(get(parent, "parentRef")) for parent in parents]
    if any(not identity(ref) or identity(ref) not in active for ref in desired):
        return False
    for parent in parents:
        conditions = get(parent, "conditions")
        if not isinstance(conditions, list):
            return False
        current = {
            condition["type"]
            for condition in conditions
            if (
                isinstance(condition, dict)
                and condition.get("observedGeneration") == generation
                and condition.get("status") == "True"
                and condition.get("type") in ("Accepted", "ResolvedRefs")
            )
        }
        if not {"Accepted", "ResolvedRefs"}.issubset(current):
            return False
    return True


def rollout(
    kubeconfig: str,
    context: str,
    namespace: str,
    route_name: str,
    stable: str,
    candidate: str,
    rule_index: int,
    weight: int | None,
    endpoint: str | None,
    policy: dict | None,
    apply: bool,
    *,
    expected_weight: int | None = None,
) -> dict:
    namespace, route_name, stable, candidate = map(
        _label, (namespace, route_name, stable, candidate)
    )
    if stable == candidate or not 0 <= rule_index <= 63:
        raise ValueError("Specify distinct backends and a valid rule index")
    if (weight is None and (endpoint is None or policy is None)) or (
        weight is not None and (endpoint is not None or policy is not None)
    ):
        raise ValueError("Supply either a weight or both Prometheus and a policy")
    target = [*_target(kubeconfig, context), "--namespace", namespace]
    document = json.loads(_kubectl(target, "get", "httproute", route_name, "-o", "json"))
    meta, refs = _route_state(document, namespace, route_name, stable, candidate, rule_index)
    weights = {ref["name"]: ref.get("weight", 1) for ref in refs}
    if expected_weight is not None and weights != {
        stable: 100 - expected_weight,
        candidate: expected_weight,
    }:
        raise ValueError("HTTPRoute weights changed outside the rehearsal")
    annotation = f"{START}-{rule_index}"
    observed = f"radea.dev/canary-observed-{rule_index}"
    annotations = meta.get("annotations", {})
    if not isinstance(annotations, dict):
        raise ValueError("Invalid HTTPRoute annotations")
    now = time.time()
    values: dict[str, float] = {}
    reasons: list[str] = []
    decision = "stage"
    record_observation = False
    if weight is None:
        decision = "hold"
        assert endpoint is not None and policy is not None
        staged = annotations.get(annotation, "0")
        try:
            started = float(staged)
        except (ValueError, TypeError):
            started = 0
        generation = meta.get("generation")
        try:
            recorded_generation, timestamp = annotations.get(observed, "").split(":", 1)
            observed_at = float(timestamp) if recorded_generation == str(generation) else 0
        except (ValueError, AttributeError):
            observed_at = 0
        if not _ready(document, generation):
            reasons.append("route_not_ready")
        elif (
            weights[stable] <= 0
            or weights[candidate] <= 0
            or weights[stable] + weights[candidate] != 100
            or not math.isfinite(started)
            or started <= 0
        ):
            reasons.append("candidate_not_staged")
        elif not math.isfinite(observed_at) or not started <= observed_at <= now:
            reasons.append("candidate_observation_required")
            record_observation = True
        elif now - observed_at < policy["window_seconds"]:
            reasons.append("candidate_window_not_ready")
        else:
            try:
                values = {key: _query(endpoint, policy["queries"][key], now) for key in SIGNALS}
            except (ValueError, OSError):
                reasons.append("telemetry_unavailable")
            else:
                if (
                    values["requests"] < 0
                    or not 0 <= values["success_rate"] <= 1
                    or values["p95_ms"] < 0
                    or not 0 <= values["sample_age_seconds"] <= policy["max_sample_age_seconds"]
                ):
                    reasons.append("invalid_or_stale_telemetry")
                elif values["requests"] < policy["min_requests"]:
                    reasons.append("insufficient_requests")
                else:
                    if values["success_rate"] < policy["min_success_rate"]:
                        reasons.append("success_rate")
                    if values["p95_ms"] > policy["max_p95_ms"]:
                        reasons.append("p95_ms")
                    if reasons:
                        decision, weight = "rollback", 0
                    else:
                        weight = next(step for step in policy["steps"] if step > weights[candidate])
                        decision = "promote" if weight == 100 else "advance"
    elif not 0 <= weight <= 100:
        raise ValueError("Candidate weight must be between 0 and 100")
    changed = False
    if apply and (weight is not None or record_observation):
        next_annotations = dict(annotations)
        if weight is None:
            next_annotations[observed] = f"{meta['generation']}:{now}"
        else:
            next_annotations[annotation] = str(now) if 0 < weight < 100 else "0"
            next_annotations.pop(observed, None)
        operations = [
            {"op": "test", "path": "/metadata/resourceVersion", "value": meta["resourceVersion"]},
            {"op": "add", "path": "/metadata/annotations", "value": next_annotations},
        ]
        for index, ref in enumerate(refs if weight is not None else []):
            assert weight is not None
            operations.append(
                {
                    "op": "add",
                    "path": f"/spec/rules/{rule_index}/backendRefs/{index}/weight",
                    "value": weight if ref["name"] == candidate else 100 - weight,
                }
            )
        _kubectl(
            target,
            "patch",
            "httproute",
            route_name,
            "--type=json",
            "--patch",
            json.dumps(operations),
        )
        changed = weight is not None
    return {
        "schema_version": "1.0",
        "command": "gateway-rollout",
        "route": route_name,
        "namespace": namespace,
        "rule_index": rule_index,
        "decision": decision,
        "reasons": reasons,
        "current_weights": weights,
        "candidate_weight": weight,
        "metrics": values,
        "applied": changed,
        "observation_recorded": apply and record_observation,
    }
