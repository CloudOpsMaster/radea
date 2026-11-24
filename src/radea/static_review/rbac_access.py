"""Evaluate one resource request against an offline Kubernetes RBAC snapshot."""

from dataclasses import asdict, dataclass
from typing import Any

from radea.core.sanitizer import clean
from radea.static_review.files import collect
from radea.static_review.yaml_loader import load_all

API = "rbac.authorization.k8s.io"
KINDS = {"Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding"}


@dataclass(frozen=True)
class Request:
    user: str
    groups: tuple[str, ...]
    verb: str
    resource: str
    api_group: str
    namespace: str
    resource_name: str | None


def _objects(value: Any) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Invalid RBAC object list")
    return value


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("Invalid RBAC rule attributes")
    return value


def _allows(rule: dict, request: Request) -> bool:
    verbs = _strings(rule.get("verbs", []))
    groups = _strings(rule.get("apiGroups", []))
    names = _strings(rule.get("resourceNames", []))
    resources = _strings(rule.get("resources", []))
    _, slash, subresource = request.resource.partition("/")
    return (
        ("*" in verbs or request.verb in verbs)
        and ("*" in groups or request.api_group in groups)
        and (
            "*" in resources
            or request.resource in resources
            or (bool(slash) and f"*/{subresource}" in resources)
        )
        and (not names or request.resource_name in names)
    )


def evaluate(path: str, request: Request, limit: int) -> dict:
    if not request.user or not request.verb or not request.resource or "*" in request.resource:
        raise ValueError("Expected a concrete RBAC user, verb and resource request")
    files, _ = collect([path], max_bytes=limit)
    if len(files) != 1:
        raise ValueError("Expected one RBAC snapshot")
    source = files[0]
    roles = {}
    bindings = []
    seen = set()
    for document in load_all(source.text, strict=True):
        if document is None:
            continue
        objects = (
            _objects(document.get("items"))
            if isinstance(document, dict) and document.get("kind") == "List"
            else _objects([document])
        )
        for obj in objects:
            kind = obj.get("kind")
            if (
                obj.get("apiVersion") != f"{API}/v1"
                or not isinstance(kind, str)
                or kind not in KINDS
            ):
                continue
            meta = obj.get("metadata")
            name = meta.get("name") if isinstance(meta, dict) else None
            namespace = meta.get("namespace", "") if isinstance(meta, dict) else ""
            if not isinstance(name, str) or not name or not isinstance(namespace, str):
                raise ValueError("RBAC resources require a valid name and namespace")
            if kind in ("Role", "RoleBinding"):
                if not namespace:
                    raise ValueError("Namespaced RBAC objects require metadata.namespace")
            elif namespace:
                raise ValueError("Cluster-scoped RBAC objects cannot declare a namespace")
            key = kind, namespace, name
            if key in seen:
                raise ValueError("Duplicate RBAC object identity")
            seen.add(key)
            if kind in ("Role", "ClusterRole"):
                roles[key] = obj
            else:
                bindings.append((key, obj))

    grants = []
    unresolved = []
    for (kind, namespace, name), binding in sorted(bindings):
        if kind == "RoleBinding" and namespace != request.namespace:
            continue
        subjects = _objects(binding.get("subjects", []))
        matches = False
        for subject in subjects:
            subject_name = subject.get("name")
            subject_kind = subject.get("kind")
            if subject_kind == "ServiceAccount":
                account_namespace = subject.get("namespace") or namespace
                matches |= bool(account_namespace) and (
                    request.user == f"system:serviceaccount:{account_namespace}:{subject_name}"
                )
            elif subject_kind == "User":
                matches |= request.user == subject_name
            elif subject_kind == "Group":
                matches |= subject_name in request.groups
        if not matches:
            continue
        ref = binding.get("roleRef")
        if not isinstance(ref, dict) or ref.get("apiGroup") != API:
            raise ValueError("Invalid roleRef for matching RBAC binding")
        role_kind, role_name = ref.get("kind"), ref.get("name")
        supported_kinds = ("ClusterRole", "Role") if kind == "RoleBinding" else ("ClusterRole",)
        if (
            not isinstance(role_kind, str)
            or role_kind not in supported_kinds
            or not isinstance(role_name, str)
        ):
            raise ValueError("Invalid roleRef for matching RBAC binding")
        role = roles.get((role_kind, namespace if role_kind == "Role" else "", role_name))
        target = {"binding": name, "kind": kind, "namespace": namespace, "role": role_name}
        if role is None:
            unresolved.append(target)
            continue
        if any(_allows(rule, request) for rule in _objects(role.get("rules", []))):
            grants.append(target)
        elif "aggregationRule" in role:
            unresolved.append(target)

    decision = "allowed" if grants else ("unknown" if unresolved else "no_grant_in_snapshot")
    return clean(
        {
            "schema_version": "1.0",
            "command": "rbac-access",
            "source": source.meta(),
            "request": {**asdict(request), "groups": list(request.groups)},
            "decision": decision,
            "grants": grants,
            "unresolved": unresolved,
        }
    )
