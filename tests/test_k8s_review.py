"""Kubernetes and Helm review: every rule fires on a minimal mutation of a clean manifest."""

import copy
import json

import pytest
import yaml
from click.testing import CliRunner

from radea.cli import main
from radea.static_review.catalog import CATALOG
from radea.static_review.runner import run_k8s

LIMIT = 8 * 1024 * 1024
DIGEST = "sha256:" + "0" * 64


def base_docs() -> list[dict]:
    labels = {"app.kubernetes.io/name": "api"}
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "api", "labels": labels},
        "spec": {
            "replicas": 3,
            "revisionHistoryLimit": 5,
            "strategy": {
                "type": "RollingUpdate",
                "rollingUpdate": {"maxSurge": 1, "maxUnavailable": 0},
            },
            "selector": {"matchLabels": dict(labels)},
            "template": {
                "metadata": {"labels": dict(labels), "annotations": {"checksum/config": "abc"}},
                "spec": {
                    "terminationGracePeriodSeconds": 30,
                    "securityContext": {"runAsNonRoot": True, "runAsUser": 10001},
                    "containers": [
                        {
                            "name": "api",
                            "image": f"registry.example.org/api:1.4.2@{DIGEST}",
                            "ports": [{"containerPort": 8080}],
                            "envFrom": [{"configMapRef": {"name": "api-config"}}],
                            "readinessProbe": {"httpGet": {"path": "/ready", "port": 8080}},
                            "livenessProbe": {"httpGet": {"path": "/healthz", "port": 8080}},
                            "startupProbe": {"httpGet": {"path": "/healthz", "port": 8080}},
                            "lifecycle": {"preStop": {"exec": {"command": ["sleep", "5"]}}},
                            "resources": {
                                "requests": {"cpu": "250m", "memory": "256Mi"},
                                "limits": {"memory": "512Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": "api"},
        "spec": {"selector": dict(labels), "ports": [{"port": 80}]},
    }
    pdb = {
        "apiVersion": "policy/v1",
        "kind": "PodDisruptionBudget",
        "metadata": {"name": "api"},
        "spec": {"minAvailable": 2, "selector": {"matchLabels": dict(labels)}},
    }
    return [deployment, service, pdb]


def container(docs):
    return docs[0]["spec"]["template"]["spec"]["containers"][0]


def pod(docs):
    return docs[0]["spec"]["template"]["spec"]


def hpa(metric="cpu", low=2, high=5):
    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": "api"},
        "spec": {
            "scaleTargetRef": {"kind": "Deployment", "name": "api"},
            "minReplicas": low,
            "maxReplicas": high,
            "metrics": [
                {
                    "type": "Resource",
                    "resource": {
                        "name": metric,
                        "target": {"type": "Utilization", "averageUtilization": 70},
                    },
                }
            ],
        },
    }


def as_statefulset(docs, **spec):
    docs[0]["kind"] = "StatefulSet"
    docs[0]["spec"].pop("strategy")
    docs[0]["spec"].update(spec)


def rbac(rule, kind="ClusterRole"):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": kind,
        "metadata": {"name": "r"},
        "rules": [rule],
    }


def mutate(fn):
    docs = base_docs()
    fn(docs)
    return docs


def selector_with_version(d):
    d[0]["spec"]["selector"]["matchLabels"]["version"] = "v1"
    d[0]["spec"]["template"]["metadata"]["labels"]["version"] = "v1"


def vpa_and_hpa(d):
    d.append(hpa())
    d.append(
        {
            "apiVersion": "autoscaling.k8s.io/v1",
            "kind": "VerticalPodAutoscaler",
            "metadata": {"name": "api"},
            "spec": {
                "targetRef": {"kind": "Deployment", "name": "api"},
                "updatePolicy": {"updateMode": "Auto"},
            },
        }
    )


def hpa_without_cpu_request(d):
    d.append(hpa())
    del container(d)["resources"]["requests"]["cpu"]


CASES = {
    "K8S001": lambda d: container(d).pop("readinessProbe"),
    "K8S002": lambda d: (
        container(d).pop("startupProbe"),
        container(d)["livenessProbe"].update(initialDelaySeconds=90),
    ),
    "K8S003": lambda d: container(d).update(image="registry.example.org/api:latest"),
    "K8S004": lambda d: container(d).update(image="registry.example.org/api:1.4.2"),
    "K8S005": lambda d: container(d).update(resources={}),
    "K8S006": lambda d: container(d).update(resources={"requests": {"cpu": "100m"}}),
    "K8S007": lambda d: container(d)["resources"]["limits"].update(memory="64Mi"),
    "K8S008": lambda d: container(d)["securityContext"].update(privileged=True),
    "K8S009": lambda d: pod(d).pop("securityContext"),
    "K8S010": lambda d: container(d)["securityContext"].update(allowPrivilegeEscalation=True),
    "K8S011": lambda d: pod(d).update(hostPID=True),
    "K8S012": lambda d: pod(d).update(volumes=[{"name": "v", "hostPath": {"path": "/x"}}]),
    "K8S013": lambda d: d[0]["spec"].update(replicas=1),
    "K8S014": lambda d: d.pop(2),
    "K8S015": lambda d: d[0]["spec"]["strategy"].update(type="Recreate"),
    "K8S016": lambda d: d[0]["spec"]["strategy"]["rollingUpdate"].update(
        maxSurge=0, maxUnavailable=0
    ),
    "K8S017": lambda d: d[0]["spec"].update(revisionHistoryLimit=0),
    "K8S018": lambda d: pod(d).update(terminationGracePeriodSeconds=2),
    "K8S019": lambda d: container(d).pop("lifecycle"),
    "K8S020": lambda d: container(d).update(
        env=[{"name": "DB_PASSWORD", "value": "hunter2hunter2"}]
    ),
    "K8S021": lambda d: d.append(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "s"},
            "data": {"k": "aHVudGVyMg=="},
        }
    ),
    "K8S022": lambda d: as_statefulset(d, volumeClaimTemplates=[{"metadata": {"name": "data"}}]),
    "K8S023": lambda d: as_statefulset(d, serviceName="api"),
    "K8S024": selector_with_version,
    "K8S025": hpa_without_cpu_request,
    "K8S026": vpa_and_hpa,
    "K8S027": lambda d: d.append(hpa(low=3, high=3)),
    "K8S028": lambda d: d.append(rbac({"apiGroups": [""], "resources": ["pods"], "verbs": ["*"]})),
    "K8S029": lambda d: d.append(
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "ClusterRoleBinding",
            "metadata": {"name": "b"},
            "roleRef": {"kind": "ClusterRole", "name": "cluster-admin"},
            "subjects": [{"kind": "ServiceAccount", "name": "api", "namespace": "x"}],
        }
    ),
    "K8S030": lambda d: d.append(
        rbac({"apiGroups": [""], "resources": ["secrets"], "verbs": ["get", "list"]})
    ),
    "K8S031": lambda d: d[0]["spec"]["template"]["metadata"].pop("annotations"),
    "K8S032": lambda d: d[1]["spec"].update(selector={"app": "typo"}),
}


def review(tmp_path, docs, name="m.yaml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump_all(docs, sort_keys=False))
    return run_k8s([str(path)], LIMIT)


def rules_in(report):
    return {f["rule"] for f in report["findings"]}


def test_clean_manifest_has_no_findings(tmp_path):
    report = review(tmp_path, base_docs())
    assert report["findings"] == [], report["findings"]


@pytest.mark.parametrize("rule", sorted(CASES))
def test_rule_fires_on_a_minimal_mutation(tmp_path, rule):
    report = review(tmp_path, mutate(CASES[rule]))
    assert rule in rules_in(report), (rule, sorted(rules_in(report)))
    # A single mutation must not light up unrelated rules beyond its natural consequences.
    assert len(rules_in(report)) <= 3, sorted(rules_in(report))


def test_examples_behave_as_documented():
    assert run_k8s(["examples/k8s/good.yaml"], LIMIT)["findings"] == []
    bad = run_k8s(["examples/k8s/bad.yaml"], LIMIT)
    assert {"K8S003", "K8S008", "K8S011", "K8S020", "K8S021", "K8S028", "K8S029"} <= rules_in(bad)
    assert bad["summary"]["by_severity"]["high"] >= 5


def test_line_numbers_point_at_the_offending_line(tmp_path):
    report = review(tmp_path, mutate(CASES["K8S011"]))
    finding = next(f for f in report["findings"] if f["rule"] == "K8S011")
    text = (tmp_path / "m.yaml").read_text().splitlines()
    assert "hostPID" in text[finding["line"] - 1]
    assert "hostPID" in finding["evidence"]


def test_secret_values_never_reach_the_report(tmp_path):
    docs = mutate(CASES["K8S020"])
    docs.append(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "s"},
            "data": {"k": "aHVudGVyMg=="},
        }
    )
    report = review(tmp_path, docs)
    blob = json.dumps(report)
    assert "hunter2" not in blob and "aHVudGVyMg" not in blob
    assert {"K8S020", "K8S021"} <= rules_in(report)


def test_hpa_without_workload_in_scope_and_ignored_files(tmp_path):
    (tmp_path / "values.yaml").write_text("replicaCount: 1\nimage: {tag: latest}\n")
    report = run_k8s([str(tmp_path)], LIMIT)
    assert report["findings"] == [] and report["summary"]["files"] == 0


def test_helm_template_syntax_is_skipped_with_a_reason(tmp_path):
    path = tmp_path / "deploy.yaml"
    path.write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {{ .Release.Name }}\n"
    )
    report = run_k8s([str(path)], LIMIT)
    assert report["summary"]["files"] == 0
    assert "helm template" in report["skipped"][0]["reason"]


def test_list_kind_is_expanded(tmp_path):
    docs = base_docs()
    container(docs).pop("readinessProbe")
    path = tmp_path / "list.yaml"
    path.write_text(yaml.safe_dump({"apiVersion": "v1", "kind": "List", "items": docs}))
    assert "K8S001" in rules_in(run_k8s([str(path)], LIMIT))


def test_yaml_alias_bomb_is_rejected_quickly(tmp_path):
    levels = ["a: &a [x, x, x, x, x, x, x, x, x]"]
    for name, prev in zip("bcdefghi", "aabcdefg", strict=False):
        levels.append(f"{name}: &{name} [{', '.join([f'*{prev}'] * 9)}]")
    path = tmp_path / "bomb.yaml"
    path.write_text("\n".join(levels) + "\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: x}\n")
    report = run_k8s([str(path)], LIMIT)  # must return, not hang or exhaust memory
    assert report["summary"]["files"] in (0, 1)


def test_oversized_explicit_file_is_an_error(tmp_path):
    path = tmp_path / "big.yaml"
    path.write_text("a: 1\n" * 100)
    with pytest.raises(ValueError, match="RADEA_MAX_INPUT_BYTES"):
        run_k8s([str(path)], 100)


def test_symlinked_files_in_directories_are_not_followed(tmp_path):
    outside = tmp_path / "outside.yaml"
    outside.write_text(yaml.safe_dump_all(mutate(CASES["K8S001"])))
    walked = tmp_path / "walked"
    walked.mkdir()
    (walked / "link.yaml").symlink_to(outside)
    report = run_k8s([str(walked)], LIMIT)
    assert report["findings"] == []
    assert report["skipped"][0]["reason"] == "symlink not followed"


# ---- Helm chart source --------------------------------------------------------------------
def make_chart(root, *, chart=None, values=None, schema=True, lock=True, template=None):
    root.mkdir(parents=True, exist_ok=True)
    meta = {"apiVersion": "v2", "name": "demo", "version": "1.0.0", "appVersion": "2.0.0"}
    meta.update(chart or {})
    (root / "Chart.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    (root / "values.yaml").write_text(
        yaml.safe_dump(
            values
            or {
                "replicaCount": 2,
                "image": {"tag": "1.2.3"},
                "resources": {"requests": {"cpu": "1"}},
            }
        )
    )
    if schema:
        (root / "values.schema.json").write_text("{}")
    if lock:
        (root / "Chart.lock").write_text("dependencies: []\n")
    (root / "templates").mkdir(exist_ok=True)
    (root / "templates" / "deployment.yaml").write_text(
        template or "kind: Deployment\nmetadata:\n  name: {{ .Release.Name }}\n"
    )
    return root


HELM_CASES = {
    "HELM001": {"chart": {"version": "latest"}},
    "HELM002": {"chart": {"appVersion": ""}},
    "HELM003": {"chart": {"dependencies": [{"name": "d", "version": "1.2.3"}]}, "lock": False},
    "HELM004": {"chart": {"dependencies": [{"name": "d", "version": "^1.2.0"}]}},
    "HELM005": {"schema": False},
    "HELM006": {"values": {"replicaCount": 2, "image": {"tag": "latest"}, "resources": {"a": 1}}},
    "HELM007": {"values": {"replicaCount": 0, "image": {"tag": "1"}, "resources": {"a": 1}}},
    "HELM008": {"values": {"replicaCount": 2, "image": {"tag": "1"}, "resources": {}}},
    "HELM009": {"template": "kind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}\n"},
}


def test_clean_chart_has_no_findings(tmp_path):
    chart = make_chart(tmp_path / "c")
    assert run_k8s([str(chart)], LIMIT)["findings"] == []


@pytest.mark.parametrize("rule", sorted(HELM_CASES))
def test_chart_rule_fires(tmp_path, rule):
    chart = make_chart(tmp_path / "c", **HELM_CASES[rule])
    report = run_k8s([str(chart)], LIMIT)
    assert rule in rules_in(report), (rule, report["findings"])


def test_chart_template_default_latest_is_flagged(tmp_path):
    template = 'image: {{ .Values.image.tag | default "latest" }}\n'
    chart = make_chart(tmp_path / "c", template=template)
    assert "HELM006" in rules_in(run_k8s([str(chart)], LIMIT))


def test_every_kubernetes_and_helm_rule_has_a_case():
    covered = set(CASES) | set(HELM_CASES)
    catalog = {k for k in CATALOG if k.startswith(("K8S", "HELM"))}
    assert covered == catalog, sorted(covered ^ catalog)


# ---- CLI contract -------------------------------------------------------------------------
def test_cli_exit_codes_and_json(tmp_path):
    runner = CliRunner()
    good = runner.invoke(main, ["k8s-review", "examples/k8s/good.yaml"])
    assert good.exit_code == 0
    bad = runner.invoke(main, ["k8s-review", "examples/k8s/bad.yaml", "--output", "json"])
    assert bad.exit_code == 2
    assert json.loads(bad.output)["summary"]["by_severity"]["high"] > 0
    never = runner.invoke(main, ["k8s-review", "examples/k8s/bad.yaml", "--fail-on", "never"])
    assert never.exit_code == 0
    missing = runner.invoke(main, ["k8s-review", str(tmp_path / "nope.yaml")])
    assert missing.exit_code == 1


def test_cli_reads_stdin():
    text = yaml.safe_dump_all(mutate(CASES["K8S003"]))
    result = CliRunner().invoke(main, ["k8s-review", "-", "--output", "json"], input=text)
    assert result.exit_code == 2
    assert "K8S003" in {f["rule"] for f in json.loads(result.output)["findings"]}


def test_rules_command_lists_catalog():
    result = CliRunner().invoke(main, ["rules", "--prefix", "k8s", "--output", "json"])
    listed = json.loads(result.output)
    assert {r["rule"] for r in listed} == {k for k in CATALOG if k.startswith("K8S")}
    assert all(r["articles"] for r in listed)


def test_catalog_copy_is_not_mutated():
    before = copy.deepcopy(CATALOG["K8S001"])
    run_k8s(["examples/k8s/bad.yaml"], LIMIT)
    assert CATALOG["K8S001"] == before
