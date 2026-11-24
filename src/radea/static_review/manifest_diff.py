"""Compare rendered Kubernetes manifests without printing their field values."""

import hashlib
import json
from functools import cache
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect
from radea.static_review.yaml_loader import load_all

Identity = tuple[str, str, str, str]


def _resources(documents: list[Any]):
    for document in documents:
        if document is None:
            continue
        if (
            isinstance(document, dict)
            and document.get("apiVersion") == "v1"
            and document.get("kind") == "List"
        ):
            items = document.get("items")
            if not isinstance(items, list):
                raise ValueError("Kubernetes List requires an items array")
            yield from items
        else:
            yield document


def _snapshot(
    path: str, max_bytes: int, *, preserve_values: bool
) -> tuple[dict[Identity, dict[str, Any]], dict]:
    sources, _ = collect((path,), max_bytes=max_bytes)
    if len(sources) != 1:
        raise ValueError("Expected one rendered Kubernetes manifest per side")
    source = sources[0]
    nodes: dict[int, Any] = {}

    @cache
    def fingerprint(node_id: int) -> str:
        value = nodes[node_id]
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            canonical = ["map", [(key, digest(value[key])) for key in sorted(value)]]
        elif isinstance(value, list):
            canonical = ["list", [digest(item) for item in value]]
        elif value is None or type(value) in (str, bool, int, float):
            canonical = ["scalar", value]
        else:
            raise ValueError("Expected JSON-compatible Kubernetes fields and values")
        encoded = json.dumps(canonical, ensure_ascii=True, allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def digest(value: Any) -> str:
        nodes[id(value)] = value
        return fingerprint(id(value))

    objects: dict[Identity, dict[str, Any]] = {}
    try:
        for document in _resources(load_all(source.text, strict=True)):
            metadata = document.get("metadata") if isinstance(document, dict) else None
            if not isinstance(metadata, dict):
                raise ValueError("Every document must be a named Kubernetes resource")
            api_version, kind, name = (
                document.get("apiVersion"),
                document.get("kind"),
                metadata.get("name"),
            )
            namespace = metadata.get("namespace", "")
            if (
                not isinstance(api_version, str)
                or not api_version.strip()
                or not isinstance(kind, str)
                or not kind.strip()
                or not isinstance(name, str)
                or not name.strip()
                or not isinstance(namespace, str)
            ):
                raise ValueError("Expected apiVersion, kind, metadata.name and a string namespace")
            group = api_version.split("/", 1)[0] if "/" in api_version else ""
            identity = group, kind, namespace, name
            if identity in objects:
                raise ValueError("Duplicate Kubernetes resource identity")
            digest(document)
            objects[identity] = (
                document
                if preserve_values
                else {key: digest(value) for key, value in document.items()}
            )
    except RecursionError:
        raise ValueError("Manifest nesting is too deep") from None
    return objects, source.meta()


def _matches(desired: Any, observed: Any) -> bool:
    pending = [(desired, observed)]
    seen: set[tuple[int, int]] = set()
    while pending:
        left, right = pending.pop()
        identity = id(left), id(right)
        if identity in seen:
            continue
        seen.add(identity)
        if type(left) is not type(right):
            return False
        if isinstance(left, dict):
            if left.keys() - right.keys():
                return False
            pending.extend((value, right[key]) for key, value in left.items())
        elif isinstance(left, list):
            if len(left) != len(right):
                return False
            pending.extend(zip(left, right))
        elif left != right:
            return False
    return True


def compare(
    before: str, after: str, max_bytes: int, *, drift: bool = False, allow_empty: bool = False
) -> dict:
    if before == after == "-":
        raise ValueError("Only one input may use stdin")
    old, old_source = _snapshot(before, max_bytes, preserve_values=drift)
    new, new_source = _snapshot(after, max_bytes, preserve_values=drift)
    if not allow_empty and not (old or new):
        raise ValueError("Both manifests are empty")
    changes: list[dict[str, Any]] = []
    for identity in sorted(old.keys() | new.keys()):
        previous, current = old.get(identity), new.get(identity)
        group, kind, namespace, name = identity
        item = {"group": group, "kind": kind, "namespace": namespace, "name": name}
        if previous is None:
            changes.append({**item, "action": "unexpected" if drift else "added", "fields": []})
        elif current is None:
            changes.append({**item, "action": "missing" if drift else "removed", "fields": []})
        else:
            if drift:
                fields = sorted(
                    key
                    for key, value in previous.items()
                    if key != "status" and (key not in current or not _matches(value, current[key]))
                )
            else:
                fields = sorted(
                    key
                    for key in previous.keys() | current.keys()
                    if previous.get(key) != current.get(key)
                )
            if fields:
                changes.append({**item, "action": "modified", "fields": fields})
    return clean(
        {
            "schema_version": "1.0",
            "command": "k8s-drift" if drift else "manifest-diff",
            "sources": {"before": old_source, "after": new_source},
            "changes": changes,
        }
    )
