"""Rule catalog: one place for severity, rationale, fix and the article each rule comes from.

Findings carry only a rule ID, so the text a human reads can never drift from what the
rule checks, and `radea rules` can list every rule without running anything.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    severity: str
    title: str
    why: str
    fix: str
    articles: tuple[int, ...] = ()


def _r(severity: str, title: str, why: str, fix: str, *articles: int) -> Rule:
    return Rule(severity, title, why, fix, tuple(articles))


CATALOG: dict[str, Rule] = {
    # ---- Kubernetes manifests -------------------------------------------------------------
    "K8S001": _r(
        "medium",
        "Container has no readiness probe",
        "Traffic is routed to pods that cannot serve yet, and a rollout cannot tell a healthy new "
        "pod from a broken one.",
        "Add a readinessProbe that checks the app's own ability to serve, not its dependencies.",
        52,
        56,
        57,
    ),
    "K8S002": _r(
        "medium",
        "Long liveness delay without a startup probe",
        "A large initialDelaySeconds on liveness delays failure detection for the whole life of "
        "the pod; a startup probe gives slow boots room without weakening liveness.",
        "Add a startupProbe and lower the liveness initialDelaySeconds.",
        56,
    ),
    "K8S003": _r(
        "high",
        "Image uses the latest tag or no tag",
        "A mutable tag means the same manifest can run different code on different nodes and "
        "rollbacks cannot restore what ran before.",
        "Pin a version tag, ideally by digest (image@sha256:...).",
        65,
        69,
    ),
    "K8S004": _r(
        "low",
        "Image is not pinned by digest",
        "Tags are mutable labels; only a digest identifies the exact content that runs.",
        "Deploy by digest and let your CD tool bump it.",
        69,
    ),
    "K8S005": _r(
        "high",
        "Container has no requests and no limits (BestEffort)",
        "BestEffort pods are scheduled blindly and are the first to be evicted under pressure.",
        "Set CPU and memory requests from measured usage percentiles and a memory limit.",
        78,
    ),
    "K8S006": _r(
        "medium",
        "Container is missing resource requests or a memory limit",
        "Requests drive scheduling and autoscaling; without a memory limit one pod can starve "
        "the node.",
        "Set cpu and memory requests and a memory limit. A CPU limit is optional.",
        77,
        78,
    ),
    "K8S007": _r(
        "high",
        "Resource limit is lower than the request",
        "The API server rejects it, or the workload never schedules as intended.",
        "Make limits greater than or equal to requests.",
        78,
    ),
    "K8S008": _r(
        "high",
        "Privileged container or dangerous capability",
        "A privileged container or SYS_ADMIN/ALL capability is close to root on the node.",
        "Remove privileged and drop all capabilities, add back only what is required.",
        65,
        80,
    ),
    "K8S009": _r(
        "medium",
        "Container may run as root",
        "Neither runAsNonRoot nor a non-zero runAsUser is set, so a compromise starts as root.",
        "Set securityContext.runAsNonRoot: true and a numeric runAsUser.",
        65,
    ),
    "K8S010": _r(
        "low",
        "Container allows privilege escalation or has a writable root filesystem",
        "Defaults leave setuid escalation and in-image tampering possible.",
        "Set allowPrivilegeEscalation: false and readOnlyRootFilesystem: true.",
        65,
    ),
    "K8S011": _r(
        "high",
        "Pod uses the host network, PID or IPC namespace",
        "Sharing the node's namespaces bypasses pod isolation.",
        "Remove hostNetwork, hostPID and hostIPC unless this is a node-level agent.",
        59,
    ),
    "K8S012": _r(
        "medium",
        "Pod mounts a hostPath volume",
        "hostPath couples the pod to a node and exposes the node's filesystem.",
        "Use a PersistentVolumeClaim, emptyDir or a projected volume instead.",
        59,
    ),
    "K8S013": _r(
        "medium",
        "Single replica without autoscaling",
        "One replica cannot survive a node drain or rollout without downtime.",
        "Run at least two replicas, or add an HorizontalPodAutoscaler with minReplicas >= 2.",
        57,
    ),
    "K8S014": _r(
        "low",
        "Multiple replicas but no PodDisruptionBudget in the reviewed files",
        "Voluntary disruptions such as node drains can evict every replica at once.",
        "Add a PodDisruptionBudget selecting these pods (it may live in another file).",
        57,
        77,
    ),
    "K8S015": _r(
        "medium",
        "Rollout strategy can cause downtime",
        "Recreate with several replicas, or maxUnavailable equal to the replica count, takes "
        "every pod out at once.",
        "Use RollingUpdate with maxUnavailable below the replica count.",
        51,
        52,
    ),
    "K8S016": _r(
        "high",
        "Rollout strategy is invalid",
        "maxSurge and maxUnavailable cannot both be zero; the rollout can never progress.",
        "Allow at least one surge or one unavailable pod.",
        52,
    ),
    "K8S017": _r(
        "medium",
        "revisionHistoryLimit is 0",
        "No old ReplicaSets are kept, so kubectl rollout undo has nothing to roll back to.",
        "Keep a realistic history, for example revisionHistoryLimit: 5.",
        58,
    ),
    "K8S018": _r(
        "medium",
        "Very short termination grace period",
        "Pods are killed before they can drain in-flight requests.",
        "Handle SIGTERM and size terminationGracePeriodSeconds above the drain time.",
        57,
    ),
    "K8S019": _r(
        "low",
        "Serving container has no preStop hook",
        "Endpoints removal and SIGTERM race; without a short preStop delay requests can hit a "
        "terminating pod.",
        "Add lifecycle.preStop with a short sleep, or drain on SIGTERM.",
        57,
    ),
    "K8S020": _r(
        "high",
        "Secret-like environment variable has a literal value",
        "The value is stored in the manifest, in Git history and in every kubectl describe.",
        "Use valueFrom.secretKeyRef or an external secrets operator.",
        38,
        55,
        68,
    ),
    "K8S021": _r(
        "medium",
        "Secret object with data in the manifest",
        "Secret values are base64, not encrypted; committing them leaks them to everyone with "
        "repository access.",
        "Use sealed secrets or an external secrets operator and keep only references in Git.",
        38,
        55,
        68,
    ),
    "K8S022": _r(
        "high",
        "StatefulSet has no serviceName",
        "serviceName is required for stable network identities.",
        "Set spec.serviceName to a headless Service.",
        59,
    ),
    "K8S023": _r(
        "low",
        "StatefulSet has no volumeClaimTemplates",
        "A StatefulSet without per-pod storage rarely needs the extra guarantees.",
        "Use a Deployment unless you need stable identity or per-pod storage.",
        59,
    ),
    "K8S024": _r(
        "high",
        "Selector uses mutable labels or does not match the pod template",
        "Selectors are immutable: a version or chart label forces delete and recreate on every "
        "release; a mismatch is rejected.",
        "Select on stable labels only (app name and instance).",
        62,
    ),
    "K8S025": _r(
        "high",
        "HPA scales on a resource the target does not request",
        "Utilisation is a percentage of the request; without a request the HPA cannot compute it.",
        "Set the matching request on every container of the target.",
        77,
        78,
    ),
    "K8S026": _r(
        "high",
        "HPA and VPA both act on the same resource of one target",
        "The two controllers fight over CPU or memory and thrash the workload.",
        "Let VPA run in Off mode, or scale on custom metrics with the HPA.",
        77,
    ),
    "K8S027": _r(
        "medium",
        "HPA maxReplicas is not above minReplicas",
        "The autoscaler can never scale out.",
        "Set maxReplicas greater than minReplicas.",
        77,
    ),
    "K8S028": _r(
        "high",
        "RBAC rule uses wildcards or escalation verbs",
        "Wildcard resources, verbs or apiGroups, and escalate/bind/impersonate, grant far more "
        "than any named requirement.",
        "List the exact resources and verbs the workload needs.",
        33,
    ),
    "K8S029": _r(
        "high",
        "Binding grants cluster-admin or a broad group",
        "cluster-admin, system:authenticated and system:unauthenticated subjects give wide "
        "access to everyone matched.",
        "Bind a narrowly scoped Role to a named service account.",
        33,
    ),
    "K8S030": _r(
        "medium",
        "RBAC rule grants cluster-wide read of Secrets",
        "Any holder can read every Secret in the cluster.",
        "Scope the rule to a namespace and to named secrets where possible.",
        33,
    ),
    "K8S031": _r(
        "low",
        "Pod uses a ConfigMap or Secret but nothing rolls it when it changes",
        "Environment variables are read once at start; pods keep stale config until restarted.",
        "Add a checksum annotation to the pod template, or use a reloader.",
        63,
        68,
    ),
    "K8S032": _r(
        "medium",
        "Service selector matches no workload in the reviewed files",
        "A selector typo gives a Service with no endpoints and no error.",
        "Compare the Service selector with the pod template labels.",
        67,
    ),
    # ---- Helm chart (source, not rendered) -------------------------------------------------
    "HELM001": _r(
        "high",
        "Chart version is missing or not semantic",
        "Helm rejects it, and a non-semantic version cannot be ordered or rolled back.",
        "Set version to a semantic version and keep appVersion separate.",
        61,
    ),
    "HELM002": _r(
        "low",
        "Chart has no appVersion",
        "version describes the package and appVersion the application; both should be meaningful.",
        "Set appVersion to the application version.",
        61,
    ),
    "HELM003": _r(
        "medium",
        "Chart has dependencies but no Chart.lock",
        "Without a lock file builds resolve whatever is newest that day.",
        "Run helm dependency update and commit Chart.lock.",
        62,
    ),
    "HELM004": _r(
        "medium",
        "Dependency version is a range",
        "Ranges make the chart non-reproducible.",
        "Pin an exact dependency version.",
        62,
    ),
    "HELM005": _r(
        "low",
        "Chart has no values.schema.json",
        "Without a schema bad values fail in production instead of in CI.",
        "Add values.schema.json and run helm lint in CI.",
        62,
    ),
    "HELM006": _r(
        "high",
        "Default image tag is latest",
        "The default silently deploys whatever latest is.",
        "Default to the chart's appVersion and pin explicitly per environment.",
        62,
        69,
    ),
    "HELM007": _r(
        "high",
        "Default values disable the workload",
        "A default of zero replicas silently deploys nothing.",
        "Default to a working replica count; disable explicitly per environment.",
        62,
    ),
    "HELM008": _r(
        "medium",
        "Default values set no resources",
        "Production defaults should carry requests, probes and security context.",
        "Bake sane requests and limits into values.yaml.",
        62,
        78,
    ),
    "HELM009": _r(
        "low",
        "Templates use config but have no checksum annotation",
        "ConfigMap changes will not roll the pods.",
        "Add checksum/config annotations to the pod template.",
        63,
        68,
    ),
    # ---- Dockerfile ------------------------------------------------------------------------
    "DF001": _r(
        "high",
        "Base image uses latest or no tag",
        "Builds are not reproducible and a base image change can break or compromise the image.",
        "Pin a specific tag and preferably a digest.",
        12,
        65,
        69,
    ),
    "DF002": _r(
        "high",
        "Image runs as root",
        "No USER instruction, or the last USER is root.",
        "Create an unprivileged user and switch to it before CMD or ENTRYPOINT.",
        12,
        65,
    ),
    "DF003": _r(
        "high",
        "Secret baked into an image layer",
        "ARG, ENV and copied key files persist in the image history.",
        "Use BuildKit secret mounts and inject credentials at runtime.",
        12,
        38,
        65,
    ),
    "DF004": _r(
        "high",
        "Remote script piped to a shell or remote ADD",
        "Unverified code from the network runs during the build.",
        "Download, verify a checksum or signature, then run.",
        34,
        65,
    ),
    "DF005": _r(
        "low",
        "Package install without cleanup or recommends flag",
        "Package caches and recommended packages bloat the image and add CVEs.",
        "Use --no-install-recommends and remove package lists in the same layer.",
        65,
    ),
    "DF006": _r(
        "medium",
        "Single-stage image contains build tooling",
        "Compilers and build tools ship to production, enlarging the attack surface.",
        "Build in one stage and copy only the artifact into a minimal runtime stage.",
        66,
    ),
    "DF007": _r(
        "low",
        "Source copied before dependencies are installed",
        "Every source change invalidates the dependency layer cache.",
        "Copy manifests, install dependencies, then copy the source.",
        65,
    ),
    "DF008": _r(
        "medium",
        "World-writable permissions or sudo",
        "chmod 777 and sudo widen what an attacker can change.",
        "Grant the narrowest permissions and avoid sudo in images.",
        12,
    ),
    "DF009": _r(
        "low",
        "Base image is not pinned by digest",
        "Tags can be moved; a digest cannot.",
        "Add @sha256:<digest> to FROM.",
        69,
    ),
    # ---- CI configuration ------------------------------------------------------------------
    "CI001": _r(
        "medium",
        "Action or include is not pinned to an immutable reference",
        "A moved tag or branch changes what runs in your pipeline without any review.",
        "Pin GitHub actions to a full commit SHA and GitLab includes to a tag or SHA.",
        5,
        34,
    ),
    "CI002": _r(
        "high",
        "Privileged trigger checks out untrusted code",
        "pull_request_target and workflow_run run with secrets; checking out the PR head runs "
        "attacker-controlled code with them.",
        "Do not check out PR code in privileged workflows, or split the workflow.",
        36,
    ),
    "CI003": _r(
        "medium",
        "Workflow has no explicit permissions",
        "The default token may be able to write; least privilege needs an explicit block.",
        "Set permissions: contents: read at the top and widen per job.",
        31,
        36,
    ),
    "CI004": _r(
        "high",
        "Untrusted event data is interpolated into a script",
        "Titles, branch names and similar fields are attacker-controlled and become shell code.",
        "Pass the value through an environment variable and quote it.",
        36,
    ),
    "CI005": _r(
        "high",
        "Script pipes a download into a shell",
        "Unverified remote code runs inside your pipeline with its credentials.",
        "Download, verify a checksum or signature, then run.",
        34,
    ),
    "CI006": _r(
        "high",
        "Pipeline prints a secret or dumps the environment",
        "Job logs are widely readable and retained; masking is best effort.",
        "Never echo credentials or run env/printenv; reference them by name.",
        32,
        38,
    ),
    "CI007": _r(
        "medium",
        "Security or quality job is allowed to fail",
        "Hard gates belong in deterministic policy; a job that cannot fail gates nothing.",
        "Remove allow_failure/continue-on-error, or document the exception.",
        31,
        40,
    ),
    "CI008": _r(
        "medium",
        "Pipeline image uses latest or no tag",
        "The job environment changes without a commit in this repository.",
        "Pin an image tag, ideally by digest.",
        5,
        69,
    ),
    "CI009": _r(
        "high",
        "Secret-like variable has a literal value in the pipeline file",
        "The value lives in Git history for everyone with repository access.",
        "Use a masked, protected CI/CD variable.",
        32,
        38,
    ),
    "CI010": _r(
        "low",
        "Deprecated only/except syntax",
        "rules: is the supported mechanism and is easier to reason about.",
        "Replace only/except with rules.",
        5,
    ),
    "CI011": _r(
        "low",
        "Job has no timeout",
        "A hung job occupies a runner until the platform default expires.",
        "Set an explicit timeout suited to the job.",
        7,
    ),
    "CI012": _r(
        "low",
        "Install command is not reproducible",
        "npm install and unlocked pip installs resolve new versions on every run.",
        "Use npm ci, and pip with a hashed lock file.",
        34,
    ),
    # ---- Vulnerability reports ------------------------------------------------------------
    "VULN001": _r(
        "high",
        "Critical or high vulnerability with a fix available",
        "A known fix exists; the exposure is a decision, not a necessity.",
        "Upgrade to the fixed version or document a justified exception.",
        34,
        37,
    ),
    "VULN002": _r(
        "medium",
        "Critical or high vulnerability with no fix available",
        "Nothing to upgrade to yet; mitigate and track it.",
        "Look for mitigations, assess reachability and record the decision.",
        37,
    ),
    "VULN003": _r(
        "low",
        "Medium or lower vulnerability",
        "Lower severity findings are tracked, not gated.",
        "Fix opportunistically when upgrading the package.",
        37,
    ),
    # ---- Flaky tests -----------------------------------------------------------------------
    "FLAKY001": _r(
        "medium",
        "Test passes and fails across runs",
        "Mixed outcomes on the same code point to timing, shared state, ordering or the "
        "environment.",
        "Quarantine with an owner and a follow-up, reproduce in a loop run, then fix.",
        6,
    ),
    "FLAKY002": _r(
        "high",
        "Test fails in every run",
        "Consistent failure is a broken test or code, not flakiness.",
        "Treat it as a defect and fix it before looking for flakiness.",
        6,
    ),
}


def lookup(rule_id: str) -> Rule:
    return CATALOG[rule_id]
