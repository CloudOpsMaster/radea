"""Failure signatures from CI, container, Kubernetes and Helm logs (articles 13, 67, 80)."""

import pytest

from radea.core import offline

CASES = [
    # (log line, expected rule name, expected category)
    ("Warning  Failed  kubelet  Error: ImagePullBackOff", "Image pull failure", "config_issue"),
    ("Failed to pull image: pull access denied for repo", "Image pull failure", "config_issue"),
    ("Error: couldn't find key password in Secret ns/db", "Container config error", "config_issue"),
    ('Error: secret "db-creds" not found', "Container config error", "config_issue"),
    ("Back-off restarting failed container app in pod x", "Pod crash loop", None),
    ("pod/x   0/1   CrashLoopBackOff   5", "Pod crash loop", None),
    ("0/3 nodes are available: 3 Insufficient cpu.", "Scheduling failure", "flaky_infra"),
    ("Warning  FailedScheduling  default-scheduler  x", "Scheduling failure", "flaky_infra"),
    ("Readiness probe failed: HTTP probe failed with statuscode: 503", "Probe failure", None),
    ("Liveness probe failed: connection refused", "Probe failure", None),
    ("The node was low on resource: ephemeral-storage. Evicted", "Pod eviction", "flaky_infra"),
    ("container exited with exit code 137", "Process killed (SIGKILL)", "flaky_infra"),
    ("Segmentation fault (core dumped)", "Crash signal", "code_error"),
    (
        'pods is forbidden: User "system:serviceaccount:ns:sa" cannot list resource "pods"',
        "RBAC denial",
        "config_issue",
    ),
    (
        'ValidatingAdmissionPolicy "x" is forbidden: User "sa" cannot get resource',
        "RBAC denial",
        "config_issue",
    ),
    (
        "error: no matches for kind KeyManagement in version x/v1",
        "Missing API or CRD",
        "config_issue",
    ),
    (
        "Error: INSTALLATION FAILED: Deployment not ready: Progress deadline exceeded",
        "Helm release failure",
        None,
    ),
    (
        "Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress",
        "Helm release failure",
        None,
    ),
    ("x509: certificate signed by unknown authority", "TLS or certificate failure", "config_issue"),
    ("curl: (6) Could not resolve host: registry.example.org", "DNS failure", "flaky_infra"),
    ("write /tmp/x: no space left on device", "Disk full", "flaky_infra"),
    ("read tcp 10.0.0.1:1->2: connection reset by peer", "Connection reset", "flaky_infra"),
    (
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
        "Docker daemon unavailable",
        "flaky_infra",
    ),
    (
        "fatal: could not read Username for 'https://git.example.org'",
        "Git access failure",
        "config_issue",
    ),
    ("remote: HTTP Basic: Access denied", "Git access failure", "config_issue"),
    (
        "ERROR: Job failed (system failure): Error in container helper",
        "CI runner system failure",
        "flaky_infra",
    ),
    ("Error: Error acquiring the state lock", "Terraform state lock", "flaky_infra"),
    (
        "Could not GET 'https://repo.example/x.jar'. Received status code 403 from server",
        "Repository authentication failure",
        "config_issue",
    ),
    (
        "Error response from daemon: unauthorized: authentication required",
        "Repository authentication failure",
        "config_issue",
    ),
    (
        "toomanyrequests: You have reached your pull rate limit",
        "Registry rate limit",
        "flaky_infra",
    ),
    (
        "Could not resolve all dependencies for configuration ':compileClasspath'",
        "Dependency resolution failure",
        "dependency_drift",
    ),
    ("npm ERR! code ERESOLVE", "Dependency resolution failure", "dependency_drift"),
    ("AssertionError: expected 3 but was 4", "Test failure", "code_error"),
    ("Tests run: 5, Failures: 2, Errors: 0", "Test failure", "code_error"),
    ("error: cannot find symbol", "Compilation failure", "code_error"),
    ("bash: kubectl: command not found", "Command not found", "config_issue"),
    ("standard_init_linux.go: exec format error", "Command not found", "config_issue"),
    (
        "yaml: line 12: mapping values are not allowed in this context",
        "Configuration syntax failure",
        "config_issue",
    ),
]


def _rule_for(line: str):
    groups = offline.matches({"s1:L1": line})
    return {rule.name: rule for rule in groups}


@pytest.mark.parametrize(("line", "name", "category"), CASES)
def test_signature_is_recognised(line, name, category):
    found = _rule_for(line)
    assert name in found, (line, sorted(found))
    if category is not None:
        assert found[name].category == category
        assert not found[name].symptom
    else:
        assert found[name].symptom


def test_symptoms_do_not_create_a_category_conflict():
    evidence = {
        "s1:L1": "Warning  Failed  OOMKilled",
        "s1:L2": "pod/x  0/1  CrashLoopBackOff  5",
        "s1:L3": "Readiness probe failed: connection refused",
    }
    result = offline.analyze("debug", evidence)
    # Memory signal is a cause category; crash loop and probe failures are only symptoms.
    assert result["category"] == "flaky_infra"
    assert {h["title"] for h in result["hypotheses"]} >= {"Memory limit signal", "Pod crash loop"}


def test_only_symptoms_stay_unknown_but_are_reported():
    result = offline.analyze("debug", {"s1:L1": "pod/x  0/1  CrashLoopBackOff  5"})
    assert result["category"] == "unknown"
    assert [h["title"] for h in result["hypotheses"]] == ["Pod crash loop"]


def test_unrelated_text_matches_nothing():
    assert offline.matches({"s1:L1": "INFO  server started on port 8080"}) == {}
    assert offline.matches({"s1:L1": "authentication failed: password required"}) == {}
