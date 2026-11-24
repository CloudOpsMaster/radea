"""An offline Kubernetes exercise graded with RADEA's static review."""

from pathlib import Path

from radea.static_review.catalog import CATALOG
from radea.static_review.files import collect
from radea.static_review.runner import run_k8s
from radea.static_review.yaml_loader import get, load_all

STARTER = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: learning-web
spec:
  selector:
    matchLabels:
      app: learning-web
  template:
    metadata:
      labels:
        app: learning-web
    spec:
      containers:
        - name: web
          image: example.invalid/web:1.0
          ports:
            - containerPort: 8080
"""


def readiness_feedback() -> str:
    rule = CATALOG["K8S001"]
    return (
        f"{rule.why}\n{rule.fix}\n"
        "The exercise application serves /ready on port 8080. "
        "Explain what happens to Service traffic when that endpoint fails."
    )


def check_readiness(path: str, limit: int) -> dict:
    if not Path(path).is_file():
        raise ValueError("Provide a local YAML submission")
    sources, _ = collect([path], max_bytes=limit)
    if len(sources) != 1:
        raise ValueError("Expected one YAML submission")
    documents = load_all(sources[0].text, strict=True)
    if len(documents) != 1:
        raise ValueError("Keep the single Deployment from the starter")
    (deployment,) = documents
    containers = get(deployment, "spec", "template", "spec", "containers")
    if (
        get(deployment, "apiVersion") != "apps/v1"
        or get(deployment, "kind") != "Deployment"
        or get(deployment, "metadata", "name") != "learning-web"
        or not isinstance(containers, list)
        or len(containers) != 1
        or get(containers[0], "name") != "web"
        or get(containers[0], "image") != "example.invalid/web:1.0"
    ):
        raise ValueError("Keep the Deployment and web container from the starter")
    review = run_k8s((path,), limit)
    probe = get(containers[0], "readinessProbe", "httpGet")
    checks = {
        "readiness_rule": bool(review["summary"]["files"])
        and all(item["rule"] != "K8S001" for item in review["findings"]),
        "exercise_endpoint": get(probe, "path") == "/ready" and get(probe, "port") == 8080,
    }
    return {"passed": all(checks.values()), "checks": checks}
