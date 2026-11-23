"""Kubernetes manifest and Helm chart review (articles 51-80). Pure functions, no cluster."""

import os
import re
from dataclasses import dataclass
from typing import Any

from radea.static_review.files import Source
from radea.static_review.findings import Finding, quote
from radea.static_review.yaml_loader import LDict, get, line_of, load_all, section

LONG_RUNNING = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet", "ReplicationController"}
WORKLOADS = LONG_RUNNING | {"Job", "CronJob", "Pod"}
SELECTOR_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "ReplicaSet"}
SECRET_NAME = re.compile(r"(?i)password|passwd|secret|token|api[_-]?key|private[_-]?key|credential")
NOT_A_SECRET = re.compile(
    r"(?i)(?:_file|_path|_name|_enabled|_url|_ref|_namespace|_secret_name|_key_name|_dir)$"
)
MUTABLE_LABELS = {"version", "app.kubernetes.io/version", "helm.sh/chart", "chart"}
SUFFIX = {
    "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60,
    "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18, "m": 1e-3,
}  # fmt: skip
SEMVER = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


@dataclass
class Doc:
    src: Source
    obj: LDict
    kind: str
    name: str

    @property
    def target(self) -> str:
        return f"{self.kind}/{self.name}"


def quantity(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([0-9]*\.?[0-9]+(?:[eE][+-]?\d+)?)([A-Za-z]{0,2})", value.strip())
    if not match or (match[2] and match[2] not in SUFFIX):
        return None
    return float(match[1]) * (SUFFIX[match[2]] if match[2] else 1)


class Review:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.docs: list[Doc] = []
        self.objects: dict[str, int] = {}

    # -- helpers -------------------------------------------------------------------------
    def add(
        self,
        rule: str,
        doc: Doc,
        node: Any = None,
        key: str | None = None,
        *,
        detail: str = "",
        evidence: str | None = None,
    ) -> None:
        line = line_of(node, key) if node is not None else None
        line = line or line_of(doc.obj)
        self.findings.append(
            Finding(
                rule,
                doc.target,
                doc.src.path,
                line,
                quote(doc.src.line(line)) if evidence is None else evidence,
                detail,
            )
        )

    def load(self, src: Source) -> str | None:
        """Parse one file; return a skip reason instead of raising."""
        try:
            documents = load_all(src.text)
        except ValueError as error:
            if "{{" in src.text:
                return "contains Helm template syntax; render it first with `helm template`"
            return str(error)
        for document in documents:
            for item in self._expand(document):
                kind, name = item.get("kind"), get(item, "metadata", "name")
                if isinstance(kind, str) and isinstance(item.get("apiVersion"), str):
                    self.docs.append(Doc(src, item, kind, str(name or "<unnamed>")))
                    self.objects[src.path] = self.objects.get(src.path, 0) + 1
        return None

    @staticmethod
    def _expand(document: Any) -> list[LDict]:
        if not isinstance(document, LDict):
            return []
        if document.get("kind") == "List" and isinstance(document.get("items"), list):
            return [item for item in document["items"] if isinstance(item, LDict)]
        return [document]

    # -- pod templates -------------------------------------------------------------------
    @staticmethod
    def pod_template(doc: Doc) -> tuple[Any, Any]:
        """Return (pod spec, pod metadata) for any workload kind, or (None, None)."""
        if doc.kind == "Pod":
            return doc.obj.get("spec"), doc.obj.get("metadata")
        if doc.kind == "CronJob":
            template = get(doc.obj, "spec", "jobTemplate", "spec", "template")
        elif doc.kind in WORKLOADS:
            template = get(doc.obj, "spec", "template")
        else:
            return None, None
        return get(template, "spec"), get(template, "metadata")

    def run(self) -> list[Finding]:
        workloads = [d for d in self.docs if d.kind in WORKLOADS]
        hpas = [d for d in self.docs if d.kind == "HorizontalPodAutoscaler"]
        vpas = [d for d in self.docs if d.kind == "VerticalPodAutoscaler"]
        pdbs = [d for d in self.docs if d.kind == "PodDisruptionBudget"]
        for doc in self.docs:
            if doc.kind in WORKLOADS:
                self.workload(doc, hpas, pdbs)
            elif doc.kind == "Secret":
                self.secret(doc)
            elif doc.kind == "HorizontalPodAutoscaler":
                self.hpa(doc, workloads, vpas)
            elif doc.kind in {"Role", "ClusterRole"}:
                self.rbac_rules(doc)
            elif doc.kind in {"RoleBinding", "ClusterRoleBinding"}:
                self.binding(doc)
            elif doc.kind == "Service":
                self.service(doc, workloads)
        return self.findings

    # -- workloads -----------------------------------------------------------------------
    def workload(self, doc: Doc, hpas: list[Doc], pdbs: list[Doc]) -> None:
        spec, meta = self.pod_template(doc)
        if not isinstance(spec, LDict):
            return
        containers = [c for c in (spec.get("containers") or []) if isinstance(c, LDict)]
        serving = any(c.get("ports") for c in containers)
        for container in containers:
            self.container(doc, spec, container)
        self.pod(doc, spec, meta, containers, serving)
        if doc.kind in LONG_RUNNING:
            self.rollout(doc, spec, meta, hpas, pdbs)

    def container(self, doc: Doc, pod: LDict, c: LDict) -> None:
        name = str(c.get("name", "?"))
        if doc.kind in LONG_RUNNING and not c.get("readinessProbe"):
            if doc.kind != "DaemonSet" or c.get("ports"):
                self.add("K8S001", doc, c, detail=f"container {name}")
        liveness = c.get("livenessProbe")
        delay = get(liveness, "initialDelaySeconds")
        if isinstance(delay, (int, float)) and delay >= 60 and not c.get("startupProbe"):
            self.add("K8S002", doc, liveness, "initialDelaySeconds", detail=f"container {name}")
        self.image(doc, c, name)
        self.resources(doc, c, name)
        self.security(doc, pod, c, name)
        for env in c.get("env") or []:
            env_name = env.get("name") if isinstance(env, LDict) else None
            if (
                isinstance(env_name, str)
                and SECRET_NAME.search(env_name)
                and not NOT_A_SECRET.search(env_name)
                and str(env.get("value", "")).strip()
                and "valueFrom" not in env
            ):
                self.add(
                    "K8S020", doc, env, "name",
                    detail=f"container {name}",
                    evidence=f"env {env_name}: literal value not shown",
                )  # fmt: skip
        if doc.kind in LONG_RUNNING and c.get("ports") and not get(c, "lifecycle", "preStop"):
            self.add("K8S019", doc, c, detail=f"container {name}")

    def image(self, doc: Doc, c: LDict, name: str) -> None:
        image = c.get("image")
        if not isinstance(image, str) or "$" in image or "{{" in image:
            return
        if "@sha256:" in image:
            return
        last = image.rsplit("/", 1)[-1]
        tag = last.split(":", 1)[1] if ":" in last else None
        rule = "K8S003" if tag in (None, "latest") else "K8S004"
        self.add(rule, doc, c, "image", detail=f"container {name}")

    def resources(self, doc: Doc, c: LDict, name: str) -> None:
        resources = c.get("resources") if isinstance(c.get("resources"), dict) else {}
        requests = resources.get("requests") if isinstance(resources, dict) else None
        limits = resources.get("limits") if isinstance(resources, dict) else None
        requests = requests if isinstance(requests, dict) else {}
        limits = limits if isinstance(limits, dict) else {}
        if not requests and not limits:
            self.add("K8S005", doc, c, detail=f"container {name}")
            return
        missing = [
            label
            for label, present in (
                ("cpu request", "cpu" in requests),
                ("memory request", "memory" in requests),
                ("memory limit", "memory" in limits),
            )
            if not present
        ]
        if missing:
            self.add(
                "K8S006", doc, c, "resources", detail=f"container {name}: {', '.join(missing)}"
            )
        for res in ("cpu", "memory"):
            low, high = quantity(requests.get(res)), quantity(limits.get(res))
            if low is not None and high is not None and high < low:
                self.add("K8S007", doc, limits, res, detail=f"container {name}: {res}")

    def security(self, doc: Doc, pod: LDict, c: LDict, name: str) -> None:
        sc = section(c, "securityContext")
        psc = section(pod, "securityContext")
        added = get(sc, "capabilities", "add") or []
        if sc.get("privileged") is True or any(str(x) in {"ALL", "SYS_ADMIN"} for x in added):
            self.add("K8S008", doc, sc or c, "privileged" if sc.get("privileged") else None,
                     detail=f"container {name}")  # fmt: skip
        non_root = sc.get("runAsNonRoot", psc.get("runAsNonRoot"))
        user = sc.get("runAsUser", psc.get("runAsUser"))
        if non_root is not True and not (isinstance(user, int) and user > 0):
            self.add("K8S009", doc, c, detail=f"container {name}")
        weak = []
        if sc.get("allowPrivilegeEscalation") is not False:
            weak.append("allowPrivilegeEscalation")
        if sc.get("readOnlyRootFilesystem") is not True:
            weak.append("writable root filesystem")
        if weak:
            self.add("K8S010", doc, c, detail=f"container {name}: {', '.join(weak)}")

    def pod(self, doc: Doc, spec: LDict, meta: Any, containers: list[LDict], serving: bool) -> None:
        for flag in ("hostNetwork", "hostPID", "hostIPC"):
            if spec.get(flag) is True:
                self.add("K8S011", doc, spec, flag, detail=flag)
        for volume in spec.get("volumes") or []:
            if isinstance(volume, LDict) and "hostPath" in volume:
                self.add("K8S012", doc, volume, "hostPath", detail=f"volume {volume.get('name')}")
        grace = spec.get("terminationGracePeriodSeconds")
        if serving and isinstance(grace, (int, float)) and grace < 10:
            self.add("K8S018", doc, spec, "terminationGracePeriodSeconds", detail=f"{grace}s")
        if doc.kind in LONG_RUNNING and self.uses_config(spec, containers):
            annotations = [
                *(get(meta, "annotations") or {}),
                *(get(doc.obj, "metadata", "annotations") or {}),
            ]
            if not any(
                re.search(r"(?i)checksum|reloader|config-hash", str(a)) for a in annotations
            ):
                self.add("K8S031", doc, spec)

    @staticmethod
    def uses_config(spec: LDict, containers: list[LDict]) -> bool:
        for volume in spec.get("volumes") or []:
            if isinstance(volume, dict) and ("configMap" in volume or "secret" in volume):
                return True
        for c in containers:
            for source in c.get("envFrom") or []:
                if isinstance(source, dict) and ("configMapRef" in source or "secretRef" in source):
                    return True
            for env in c.get("env") or []:
                ref = get(env, "valueFrom")
                if isinstance(ref, dict) and ("configMapKeyRef" in ref or "secretKeyRef" in ref):
                    return True
        return False

    # -- rollout, replicas, selectors ------------------------------------------------------
    def rollout(self, doc: Doc, spec: LDict, meta: Any, hpas: list[Doc], pdbs: list[Doc]) -> None:
        body = section(doc.obj, "spec")
        labels = get(meta, "labels") or {}
        replicas = body.get("replicas")
        count = replicas if isinstance(replicas, int) else 1
        floor = self.hpa_min(doc, hpas)
        if doc.kind in {"Deployment", "StatefulSet"}:
            if floor is None and count <= 1:
                self.add("K8S013", doc, body, "replicas")
            effective = max(count, floor or 0)
            if effective >= 2 and not any(self.pdb_matches(p, labels) for p in pdbs):
                self.add("K8S014", doc, body, "replicas" if "replicas" in body else None)
        if doc.kind == "Deployment":
            strategy = section(body, "strategy")
            if strategy.get("type") == "Recreate" and count >= 2:
                self.add("K8S015", doc, strategy, "type", detail="Recreate")
            update = strategy.get("rollingUpdate")
            surge, unavailable = get(update, "maxSurge"), get(update, "maxUnavailable")
            if update and self.zero(surge) and self.zero(unavailable):
                self.add("K8S016", doc, update)
            elif update and count >= 2 and self.all_unavailable(unavailable, count):
                self.add(
                    "K8S015", doc, update, "maxUnavailable", detail=f"maxUnavailable={unavailable}"
                )
        if body.get("revisionHistoryLimit") == 0:
            self.add("K8S017", doc, body, "revisionHistoryLimit")
        if doc.kind in SELECTOR_KINDS:
            self.selector(doc, body, labels)
        if doc.kind == "StatefulSet":
            if not body.get("serviceName"):
                self.add("K8S022", doc, body)
            if not body.get("volumeClaimTemplates"):
                self.add("K8S023", doc, body)

    @staticmethod
    def zero(value: Any) -> bool:
        return value in (0, "0", "0%")

    @staticmethod
    def all_unavailable(value: Any, count: int) -> bool:
        if isinstance(value, int):
            return value >= count
        return isinstance(value, str) and value.strip() == "100%"

    def selector(self, doc: Doc, body: LDict, template_labels: Any) -> None:
        match = get(body, "selector", "matchLabels")
        if not isinstance(match, dict):
            return
        bad = sorted(set(match) & MUTABLE_LABELS)
        if bad:
            self.add("K8S024", doc, match, bad[0], detail=f"mutable label {bad[0]}")
        elif isinstance(template_labels, dict) and any(
            template_labels.get(k) != v for k, v in match.items()
        ):
            self.add("K8S024", doc, match, detail="selector does not match the pod template labels")

    @staticmethod
    def hpa_min(doc: Doc, hpas: list[Doc]) -> int | None:
        for hpa in hpas:
            ref = get(hpa.obj, "spec", "scaleTargetRef")
            if get(ref, "kind") == doc.kind and get(ref, "name") == doc.name:
                low = get(hpa.obj, "spec", "minReplicas")
                return low if isinstance(low, int) else 1
        return None

    @staticmethod
    def pdb_matches(pdb: Doc, labels: Any) -> bool:
        selector = get(pdb.obj, "spec", "selector")
        if not isinstance(selector, dict):
            return True  # nothing to compare against; do not claim it is missing
        if selector.get("matchExpressions"):
            return True  # cannot evaluate expressions statically
        match = selector.get("matchLabels") or {}
        return isinstance(labels, dict) and all(labels.get(k) == v for k, v in match.items())

    # -- other kinds -----------------------------------------------------------------------
    def secret(self, doc: Doc) -> None:
        if doc.obj.get("type") == "kubernetes.io/service-account-token":
            return
        keys = [*(doc.obj.get("data") or {}), *(doc.obj.get("stringData") or {})]
        if keys:
            shown = ", ".join(map(str, keys[:10]))
            self.add(
                "K8S021",
                doc,
                doc.obj,
                "data" if "data" in doc.obj else "stringData",
                evidence=f"keys: {shown} (values not shown)",
            )

    def hpa(self, doc: Doc, workloads: list[Doc], vpas: list[Doc]) -> None:
        spec = section(doc.obj, "spec")
        low, high = spec.get("minReplicas", 1), spec.get("maxReplicas")
        if isinstance(low, int) and isinstance(high, int) and high <= low:
            self.add("K8S027", doc, spec, "maxReplicas", detail=f"min {low}, max {high}")
        ref = spec.get("scaleTargetRef")
        used = self.hpa_resources(spec)
        target = next(
            (w for w in workloads
             if w.kind == get(ref, "kind") and w.name == get(ref, "name")), None)  # fmt: skip
        if target is not None and used:
            pod, _ = self.pod_template(target)
            for c in get(pod, "containers") or []:
                requests = get(c, "resources", "requests") or {}
                for resource in sorted(used):
                    if resource not in requests:
                        self.add(
                            "K8S025", doc, spec, detail=f"{get(c, 'name')}: no {resource} request"
                        )
        for vpa in vpas:
            vref = get(vpa.obj, "spec", "targetRef")
            mode = get(vpa.obj, "spec", "updatePolicy", "updateMode") or "Auto"
            if (
                get(vref, "kind") == get(ref, "kind")
                and get(vref, "name") == get(ref, "name")
                and mode != "Off"
                and used
            ):
                controlled = {"cpu", "memory"}
                for policy in get(vpa.obj, "spec", "resourcePolicy", "containerPolicies") or []:
                    listed = get(policy, "controlledResources")
                    if isinstance(listed, list):
                        controlled &= {str(x) for x in listed}
                overlap = sorted(used & controlled)
                if overlap:
                    self.add("K8S026", doc, spec, detail=f"{vpa.target} also controls {overlap[0]}")

    @staticmethod
    def hpa_resources(spec: LDict) -> set[str]:
        used = set()
        if spec.get("targetCPUUtilizationPercentage") is not None:
            used.add("cpu")
        for metric in spec.get("metrics") or []:
            resource = get(metric, "resource")
            if (
                get(metric, "type") == "Resource"
                and get(resource, "target", "type") == "Utilization"
            ):
                used.add(str(get(resource, "name")))
        return used

    def rbac_rules(self, doc: Doc) -> None:
        for rule in doc.obj.get("rules") or []:
            if not isinstance(rule, LDict):
                continue
            verbs, resources = rule.get("verbs") or [], rule.get("resources") or []
            groups = rule.get("apiGroups") or []
            wild = [k for k in ("verbs", "resources", "apiGroups") if "*" in (rule.get(k) or [])]
            danger = sorted({"escalate", "bind", "impersonate"} & {str(v) for v in verbs})
            if wild or danger:
                self.add("K8S028", doc, rule, wild[0] if wild else "verbs",
                         detail=", ".join(wild or danger))  # fmt: skip
            reads = {"get", "list", "watch"} & {str(v) for v in verbs}
            if doc.kind == "ClusterRole" and "secrets" in resources and reads and "*" not in groups:
                self.add("K8S030", doc, rule, "resources")

    def binding(self, doc: Doc) -> None:
        if get(doc.obj, "roleRef", "name") == "cluster-admin":
            self.add("K8S029", doc, doc.obj.get("roleRef"), "name", detail="cluster-admin")
        for subject in doc.obj.get("subjects") or []:
            name = get(subject, "name")
            if name in {"system:authenticated", "system:unauthenticated", "system:anonymous"}:
                self.add("K8S029", doc, subject, "name", detail=str(name))

    def service(self, doc: Doc, workloads: list[Doc]) -> None:
        selector = get(doc.obj, "spec", "selector")
        if not isinstance(selector, dict) or not selector or not workloads:
            return
        if get(doc.obj, "spec", "type") == "ExternalName":
            return
        for workload in workloads:
            _, meta = self.pod_template(workload)
            labels = get(meta, "labels")
            if isinstance(labels, dict) and all(labels.get(k) == v for k, v in selector.items()):
                return
        self.add("K8S032", doc, doc.obj.get("spec"), "selector")


# ---- Helm chart source (not rendered) -----------------------------------------------------
def review_chart(
    chart: Source, siblings: dict[str, Source], chart_dir: str | None
) -> list[Finding]:
    findings: list[Finding] = []

    def emit(rule: str, src: Source, line: int | None, target: str, detail: str = "") -> None:
        findings.append(Finding(rule, target, src.path, line, quote(src.line(line)), detail))

    try:
        documents = load_all(chart.text)
    except ValueError:
        return findings
    meta = documents[0] if documents and isinstance(documents[0], LDict) else LDict()
    name = f"Chart/{meta.get('name', '<unnamed>')}"
    version = meta.get("version")
    if not isinstance(version, str) or not SEMVER.match(version):
        emit("HELM001", chart, line_of(meta, "version"), name)
    if not meta.get("appVersion"):
        emit("HELM002", chart, line_of(meta), name)
    dependencies = [d for d in meta.get("dependencies") or [] if isinstance(d, LDict)]
    exists = os.path.exists
    if dependencies and chart_dir is not None and not exists(os.path.join(chart_dir, "Chart.lock")):
        emit("HELM003", chart, line_of(meta, "dependencies"), name)
    for dependency in dependencies:
        if re.search(r"[\^~*xX<>|]|\s-\s", str(dependency.get("version", ""))):
            emit("HELM004", chart, line_of(dependency, "version"), name,
                 f"{dependency.get('name')}: {dependency.get('version')}")  # fmt: skip
    if chart_dir is not None and not exists(os.path.join(chart_dir, "values.schema.json")):
        emit("HELM005", chart, line_of(meta), name)
    values = siblings.get("values.yaml")
    if values is not None:
        _review_values(values, name, findings)
    templates = [s for p, s in siblings.items() if p.startswith("templates/")]
    texts = "\n".join(s.text for s in templates)
    if re.search(r"""default\s+["']latest["']""", texts):
        for src in templates:
            for number, text in enumerate(src.lines, 1):
                if re.search(r"""default\s+["']latest["']""", text):
                    emit("HELM006", src, number, name)
    uses_config = re.search(r"kind:\s*(?:ConfigMap|Secret)|configMapRef|secretRef", texts)
    if templates and uses_config and "checksum/" not in texts:
        emit("HELM009", templates[0], None, name)
    return findings


def _review_values(values: Source, name: str, findings: list[Finding]) -> None:
    try:
        documents = load_all(values.text)
    except ValueError:
        return
    data = documents[0] if documents and isinstance(documents[0], LDict) else LDict()

    def emit(rule: str, line: int | None, detail: str = "") -> None:
        findings.append(Finding(rule, name, values.path, line, quote(values.line(line)), detail))

    tag = get(data, "image", "tag")
    if isinstance(tag, str) and tag.strip().lower() == "latest":
        emit("HELM006", line_of(get(data, "image"), "tag"))
    if data.get("replicaCount") == 0:
        emit("HELM007", line_of(data, "replicaCount"))
    if "resources" in data and not data["resources"]:
        emit("HELM008", line_of(data, "resources"))
