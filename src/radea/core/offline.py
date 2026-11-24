"""Bounded rule analysis of sanitized evidence; no network or inference dependencies."""

import json
import re
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    name: str
    category: str
    pattern: str
    advice: str
    severity: str = "medium"
    # A symptom (CrashLoopBackOff, failed probe, failed Helm release) is reported but says
    # nothing about the cause, so it never decides or conflicts with the failure category.
    symptom: bool = False


RULES = (
    Rule(
        "Missing dependency",
        "dependency_drift",
        r"ModuleNotFoundError:|ImportError:|No matching distribution found|Cannot find module",
        "Compare the installed dependencies and lockfile with the failing interpreter.",
    ),
    Rule(
        "Syntax failure",
        "code_error",
        r"SyntaxError:|IndentationError:|TabError:",
        "Compile the cited source with the same language version used by the job.",
    ),
    Rule(
        "Runtime exception",
        "code_error",
        r"(?:TypeError|NameError|AttributeError|ZeroDivisionError|KeyError|IndexError):",
        "Reproduce the cited exception and inspect its traceback and inputs.",
    ),
    Rule(
        "Permission failure",
        "config_issue",
        r"PermissionError:|permission denied|access denied",
        "Check the effective user and the minimum permissions required for this operation.",
    ),
    Rule(
        "Missing file",
        "config_issue",
        r"FileNotFoundError:|IsADirectoryError:|NotADirectoryError:|no such file or directory",
        "Check the working directory, expected file and upstream artifact availability.",
    ),
    Rule(
        "Memory limit signal",
        "flaky_infra",
        r"\bOOMKilled\b|out of memory|MemoryError:",
        "Inspect measured peak memory and the configured job/container memory limit.",
        "high",
    ),
    Rule(
        "Timeout signal",
        "flaky_infra",
        r"\btimed out\b|\bTimeoutError\b|TimeoutExpired:|deadline exceeded",
        "Check request latency and service health; a timeout alone does not establish cause.",
    ),
    Rule(
        "Connection failure",
        "flaky_infra",
        r"connection refused|ConnectionRefusedError:",
        "Check the endpoint and service readiness from the same runner network.",
    ),
    Rule(
        "Image pull failure",
        "config_issue",
        r"ImagePullBackOff|ErrImagePull|Back-off pulling image|pull access denied|manifest unknown",
        "Check the image and tag exist and the namespace has working registry credentials.",
        "high",
    ),
    Rule(
        "Container config error",
        "config_issue",
        r"CreateContainerConfigError|(?:secret|configmap) \"[^\"]+\" not found|couldn't find key",
        "Check the referenced Secret or ConfigMap exists in the pod's namespace and has the key.",
        "high",
    ),
    Rule(
        "Pod crash loop",
        "unknown",
        r"CrashLoopBackOff|Back-off restarting failed container",
        "Read the previous container logs and last state (kubectl logs --previous, describe pod).",
        symptom=True,
    ),
    Rule(
        "Scheduling failure",
        "flaky_infra",
        r"FailedScheduling|Insufficient (?:cpu|memory|pods)|untolerated taint|Unschedulable",
        "Compare pod requests with node allocatable capacity, taints and affinity rules.",
        "high",
    ),
    Rule(
        "Probe failure",
        "unknown",
        r"(?:Readiness|Liveness|Startup) probe failed",
        "Compare probe path, port and timing with the application's real startup and health.",
        symptom=True,
    ),
    Rule(
        "Pod eviction",
        "flaky_infra",
        r"\bEvicted\b|DiskPressure|MemoryPressure|node was low on resource",
        "Check node pressure, ephemeral storage use and the pod's requests and QoS class.",
    ),
    Rule(
        "Process killed (SIGKILL)",
        "flaky_infra",
        r"exit(?:ed with)? (?:code|status):? 137|signal: killed",
        "Exit 137 means SIGKILL, commonly the OOM killer; compare peak memory with the limit.",
        "high",
    ),
    Rule(
        "Crash signal",
        "code_error",
        r"Segmentation fault|SIGSEGV|exit(?:ed with)? (?:code|status):? 139",
        "Reproduce with the same binary and inputs; inspect the core dump or sanitizer output.",
    ),
    Rule(
        "RBAC denial",
        "config_issue",
        r"is forbidden: User|cannot (?:get|list|watch|create|update|patch|delete) resource",
        "Compare the service account's Role/ClusterRole rules with the verb and resource named.",
        "high",
    ),
    Rule(
        "Missing API or CRD",
        "config_issue",
        r"no matches for kind|resource mapping not found|could not find the requested resource",
        "Check the CRD or API version is installed and served before applying the resource.",
    ),
    Rule(
        "Helm release failure",
        "unknown",
        r"INSTALLATION FAILED|UPGRADE FAILED|Progress deadline exceeded"
        r"|another operation \(install/upgrade/rollback\) is in progress"
        r"|cannot re-use a name that is still in use",
        "Run helm status and list namespace events; the failing pod usually names the cause.",
        symptom=True,
    ),
    Rule(
        "TLS or certificate failure",
        "config_issue",
        r"x509:|certificate verify failed|unable to get local issuer certificate"
        r"|PKIX path building",
        "Check the trust store, certificate chain, expiry and the hostname used by the client.",
    ),
    Rule(
        "DNS failure",
        "flaky_infra",
        r"no such host|Temporary failure in name resolution|Could not resolve host"
        r"|UnknownHostException",
        "Resolve the name from the same network; check cluster DNS or the runner's resolver.",
    ),
    Rule(
        "Disk full",
        "flaky_infra",
        r"no space left on device|ENOSPC|disk quota exceeded",
        "Check free space and inode use on the runner or node, and cache or artifact growth.",
        "high",
    ),
    Rule(
        "Connection reset",
        "flaky_infra",
        r"connection reset by peer|ECONNRESET|Broken pipe|TLS handshake timeout|i/o timeout",
        "Check the peer's health and any proxy or load balancer between the two ends.",
    ),
    Rule(
        "Docker daemon unavailable",
        "flaky_infra",
        r"Cannot connect to the Docker daemon|Is the docker daemon running",
        "Check the Docker service, socket mount or DinD sidecar on the executor.",
    ),
    Rule(
        "Git access failure",
        "config_issue",
        r"could not read Username|Repository not found|Authentication failed for"
        r"|Permission denied \(publickey\)|HTTP Basic: Access denied",
        "Check the token or key, its scope, and that the repository path exists.",
    ),
    Rule(
        "CI runner system failure",
        "flaky_infra",
        r"runner_system_failure|Job failed \(system failure\)|Error in container helper",
        "Check the runner pod events and memory limits; a system failure is not a script error.",
        "high",
    ),
    Rule(
        "Terraform state lock",
        "flaky_infra",
        r"Error acquiring the state lock",
        "Find the run holding the lock before considering any force-unlock.",
    ),
    Rule(
        "Repository authentication failure",
        "config_issue",
        r"Received status code (?:401|403)|401 Unauthorized|403 Forbidden"
        r"|unauthorized: authentication required|denied: requested access",
        "Check the credentials, token scope and repository permission used by this job.",
        "high",
    ),
    Rule(
        "Registry rate limit",
        "flaky_infra",
        r"toomanyrequests|pull rate limit|429 Too Many Requests",
        "Use an authenticated pull or a registry mirror and retry after the window resets.",
    ),
    Rule(
        "Dependency resolution failure",
        "dependency_drift",
        r"Could not resolve (?:all )?(?:dependencies|artifacts)|Could not find artifact"
        r"|ERESOLVE|Failed to collect dependencies",
        "Compare the requested versions with the lockfile and what the repository serves.",
    ),
    Rule(
        "Test failure",
        "code_error",
        r"AssertionError|AssertionFailedError|Tests run:[^\n]{0,200}Failures: [1-9]|Tests? FAILED",
        "Re-run the named test alone and read its assertion message and inputs.",
    ),
    Rule(
        "Compilation failure",
        "code_error",
        r"cannot find symbol|COMPILATION ERROR|Compilation failure|error TS\d+"
        r"|cannot find package",
        "Build the cited file with the same toolchain version as the job.",
    ),
    Rule(
        "Command not found",
        "config_issue",
        r"command not found|executable file not found|exec format error",
        "Check the tool is installed in the job image and built for its CPU architecture.",
    ),
    Rule(
        "Configuration syntax failure",
        "config_issue",
        r"mapping values are not allowed|could not find expected|error validating data"
        r"|unknown field \"|yaml: line \d+|Invalid pipeline configuration",
        "Validate the cited file against its schema or linter before running it again.",
    ),
)
COMPILED = tuple((rule, re.compile(rule.pattern, re.IGNORECASE)) for rule in RULES)
STAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")


def matches(evidence: dict[str, str]) -> dict:
    groups = defaultdict(list)
    for ref, line in evidence.items():
        for rule, pattern in COMPILED:
            if pattern.search(line):
                groups[rule].append((ref, line))
    return groups


def analyze(kind: str, evidence: dict[str, str]) -> dict:
    """Claims describe observed signals, never assert an inferred root cause."""
    groups = matches(evidence)
    if kind == "debug":
        categories = {rule.category for rule in groups if not rule.symptom}
        return {
            "category": next(iter(categories)) if len(categories) == 1 else "unknown",
            "hypotheses": [
                {
                    "title": rule.name,
                    "description": "Observed log signal; cause is unverified.",
                    "verify": rule.advice,
                    "confidence": "low",
                    "source_line": rows[0][1],
                    "evidence_ids": [rows[0][0]],
                }
                for rule, rows in groups.items()
            ],
        }
    if kind == "iac-review":
        findings = []
        for ref, line in evidence.items():
            resource = json.loads(line) if ref.startswith("plan:") else None
            if resource and "delete" in resource["actions"]:
                findings.append(
                    {
                        "title": "Destructive plan action",
                        "severity": "high",
                        "description": "Plan includes deletion; review the policy gate.",
                        "resource": resource["resource"],
                        "evidence_ids": [ref],
                    }
                )
        return {
            "summary": "Local checks only: plan deletion signals and literal IAM wildcards. "
            "No findings does not mean the configuration is secure.",
            "findings": findings[:100],
        }
    timeline = []
    for ref, line in evidence.items():
        stamp = STAMP.search(line)
        if stamp and any(pattern.search(line) for _, pattern in COMPILED):
            timeline.append(
                {
                    "time": stamp[0],
                    "event": "Observed failure signal",
                    "source_line": line,
                    "evidence_ids": [ref],
                }
            )
    return {
        "patterns": [
            {
                "label": rule.name,
                "description": rule.advice,
                "severity": rule.severity,
                "count": len(rows),
                "example_line": rows[0][1],
                "evidence_ids": [rows[0][0]],
            }
            for rule, rows in groups.items()
        ],
        "timeline": timeline[:100],
        "probable_cause": "Unknown; deterministic signals do not establish causation.",
        "postmortem_draft": "Review the cited observations and supplied metric comparisons. "
        "A human must establish impact, cause and follow-up actions.",
    }
