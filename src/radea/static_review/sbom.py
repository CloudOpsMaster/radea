"""Link scanner findings to a CycloneDX component inventory and dependency graph."""

import json
from collections import defaultdict, deque
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect
from radea.static_review.vuln import parse_report


def _objects(value: Any, field: str) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Expected a CycloneDX {field} list")
    return value


def _observations(
    path: str, bom_sha256: str, limit: int,
) -> tuple[dict[tuple[str, str], set[str]], dict]:
    inputs, _ = collect([path], max_bytes=limit)
    if len(inputs) != 1:
        raise ValueError("Expected one runtime observation file")
    source = inputs[0]
    try:
        data = json.loads(source.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid runtime observation JSON") from None
    if not isinstance(data, dict) or data.get("bom_sha256") != bom_sha256:
        raise ValueError("Runtime observations must identify the exact SBOM SHA-256")
    rows = data.get("observations")
    if not isinstance(rows, list) or len(rows) > 25_000:
        raise ValueError("Expected up to 25000 runtime observations")
    observed: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"bom_ref", "id", "symbol"}:
            raise ValueError("Each runtime observation needs a bom_ref, id and symbol")
        if any(
            not isinstance(value, str) or not value.strip() or len(value) > 512
            for value in row.values()
        ):
            raise ValueError("Invalid runtime observation reference")
        observed[(row["bom_ref"], row["id"])].add(row["symbol"])
    return observed, source.meta()


def analyse(bom_path: str, scan_path: str, limit: int, *, runtime: str | None = None) -> dict:
    if (bom_path, scan_path, runtime).count("-") > 1:
        raise ValueError("Only one input may use stdin")
    # Collect separately so an identical path is validated against both input schemas.
    inputs = []
    for path in (bom_path, scan_path):
        files, _ = collect([path], max_bytes=limit)
        if len(files) != 1:
            raise ValueError("Expected one input file per argument")
        inputs.append(files[0])
    bom, scan = inputs
    sources = {"sbom": bom.meta(), "scan": scan.meta()}
    observed: dict[tuple[str, str], set[str]] = {}
    if runtime is not None:
        observed, sources["runtime"] = _observations(runtime, bom.sha256, limit)
    matched_observations = set()
    try:
        data = json.loads(bom.text)
    except (ValueError, RecursionError):
        raise ValueError("Invalid CycloneDX JSON") from None
    if not isinstance(data, dict) or data.get("bomFormat") != "CycloneDX":
        raise ValueError("Expected a CycloneDX JSON SBOM")
    metadata = data.get("metadata")
    root = metadata.get("component") if isinstance(metadata, dict) else None
    root_ref = root.get("bom-ref") if isinstance(root, dict) else None
    pending = deque(_objects(data.get("components", []), "components"))
    if isinstance(root, dict):
        pending.appendleft(root)
    by_ref: set[str] = set()
    by_purl: dict[str, list[dict]] = defaultdict(list)
    by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
    component_count = 0
    while pending:
        component = pending.popleft()
        component_count += 1
        if component_count > 25_000:
            raise ValueError("SBOM exceeds 25000 components")
        ref, name, version, purl = (
            component.get(key) for key in ("bom-ref", "name", "version", "purl")
        )
        if ref is not None:
            if not isinstance(ref, str) or not ref or ref in by_ref:
                raise ValueError("CycloneDX bom-ref identifiers must be unique nonempty strings")
            by_ref.add(ref)
        if isinstance(purl, str) and purl:
            by_purl[purl].append(component)
        if isinstance(name, str) and isinstance(version, str) and name and version:
            by_name[name, version].append(component)
        pending.extend(_objects(component.get("components", []), "nested components"))
    edges: dict[str, list[str]] = {}
    for record in _objects(data.get("dependencies", []), "dependencies"):
        ref = record.get("ref")
        targets = record.get("dependsOn", [])
        if (
            not isinstance(ref, str)
            or ref in edges
            or not isinstance(targets, list)
            or not all(isinstance(target, str) for target in targets)
        ):
            raise ValueError("Invalid CycloneDX dependency record")
        edges[ref] = targets
    distance: dict[str, int] = {}
    if isinstance(root_ref, str) and root_ref in edges:
        distance[root_ref] = 0
        queue = deque([root_ref])
        while queue:
            ref = queue.popleft()
            for target in edges.get(ref, []):
                if target not in distance:
                    distance[target] = distance[ref] + 1
                    queue.append(target)
    results = []
    for vulnerability in parse_report(scan):
        candidates = (
            by_purl.get(vulnerability.purl, [])
            if vulnerability.purl
            else by_name.get((vulnerability.package, vulnerability.version), [])
        )
        match = candidates[0] if len(candidates) == 1 else None
        ref = match.get("bom-ref") if match is not None else None
        depth = distance.get(ref) if isinstance(ref, str) else None
        identity = (ref, vulnerability.id) if isinstance(ref, str) else None
        evidence = observed.get(identity) if identity is not None else None
        if identity is not None and evidence:
            matched_observations.add(identity)
        results.append(
            {
                "id": vulnerability.id,
                "package": vulnerability.package,
                "version": vulnerability.version,
                "severity": vulnerability.severity,
                "match": ("purl" if vulnerability.purl else "name_version")
                if match is not None
                else ("ambiguous" if candidates else "unmatched"),
                "bom_ref": ref,
                "dependency_depth": depth,
                **({
                    "runtime_reachability": "reported_observed" if evidence else "unknown",
                    "observed_symbol_count": len(evidence) if evidence else 0,
                } if runtime is not None else {}),
            }
        )
    return clean(
        {
            "schema_version": "1.0",
            "command": "sbom-review",
            "sources": sources,
            "components": component_count,
            "root_dependency_graph_present": bool(distance),
            "findings": results,
            **({"unmatched_runtime_pairs": len(observed.keys() - matched_observations)}
               if runtime is not None else {}),
        }
    )
