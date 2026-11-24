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
        "Add a checksum annotation or reloader. For hot-read volume mounts, declare "
        "radea.dev/reloadable-config-volumes after verifying update behavior.",
        60,
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
    "K8S033": _r(
        "medium",
        "Progressive rollout promotes without metric analysis",
        "A canary that only waits cannot tell a healthy release from a broken one, so a bad "
        "version still reaches everyone.",
        "Add an analysis (Argo AnalysisTemplate or Flagger metrics/webhooks) with thresholds "
        "that abort and roll back.",
        54,
    ),
    "K8S034": _r(
        "medium",
        "Canary starts with a large share of traffic",
        "The point of a canary is a small blast radius; a first step of half the traffic, or a "
        "single step to the whole fleet, removes it.",
        "Start at a small weight and ramp over several steps with bake windows.",
        54,
    ),
    "K8S035": _r(
        "medium",
        "Blue-green flips without validating the new side first",
        "Without a preview service and a pre-promotion check the switch is the first time the "
        "new version meets real traffic.",
        "Set previewService, run prePromotionAnalysis and set autoPromotionEnabled: false "
        "until it passes.",
        53,
    ),
    "K8S036": _r(
        "high",
        "Custom resource has invalid served or storage versions",
        "A CRD needs unique version names, a single storage version and an API version clients "
        "can access.",
        "Name each version, mark exactly one as storage and serve at least one version.",
        71,
    ),
    "K8S037": _r(
        "high",
        "Custom resource version lacks an object schema",
        "The API server uses a structural schema to validate and prune custom resources.",
        "Define schema.openAPIV3Schema with type: object for each served or storage version "
        "and validate the full schema with the Kubernetes API.",
        71,
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
    # ---- Terraform source ------------------------------------------------------------------
    "TF001": _r(
        "high",
        "Admin or database port open to the whole internet",
        "SSH, RDP and database ports reachable from 0.0.0.0/0 are scanned and attacked "
        "within minutes of exposure.",
        "Restrict the source to a VPN, bastion or known CIDR, or use a managed access path.",
        11,
        16,
        33,
    ),
    "TF002": _r(
        "medium",
        "Ingress open to the whole internet",
        "World-open ingress is sometimes intended (public HTTPS) but always deserves a review.",
        "Confirm the exposure is intended and limit ports and protocols to what is served.",
        16,
        33,
    ),
    "TF003": _r(
        "high",
        "Secret-like attribute has a literal value",
        "The value is in the repository, the state file and every plan output.",
        "Take it from a secrets manager or a sensitive variable and rotate the exposed value.",
        32,
        38,
        11,
    ),
    "TF004": _r(
        "medium",
        "Encryption is explicitly disabled",
        "Data at rest is stored in the clear, which compliance regimes rarely accept.",
        "Enable encryption and manage the key explicitly.",
        16,
        31,
    ),
    "TF005": _r(
        "high",
        "Resource is configured as publicly accessible",
        "Public databases and public-read buckets are a leading cause of data exposure.",
        "Make it private and expose it through a controlled front door.",
        16,
        33,
    ),
    "TF006": _r(
        "medium",
        "Provider or module version is not pinned",
        "Unpinned or open-ended versions change behaviour between plans; models also assume the "
        "newest syntax.",
        "Pin an exact or pessimistic (~>) version and commit the dependency lock file.",
        16,
        11,
    ),
    "TF007": _r(
        "medium",
        "Safety net for destructive operations is switched off",
        "skip_final_snapshot, force_destroy and disabled deletion protection let a plan destroy "
        "data with no way back.",
        "Keep deletion protection and a final snapshot; remove the override.",
        16,
        58,
    ),
    "TF008": _r(
        "low",
        "Stateful resource has no prevent_destroy lifecycle guard",
        "A destroy or replace of a database, bucket or key should need an explicit decision.",
        "Add lifecycle { prevent_destroy = true } and remove it deliberately when needed.",
        16,
    ),
    "CI013": _r(
        "medium",
        "helm upgrade or install without atomic rollback and a timeout",
        "A failed upgrade leaves a half-applied release; --atomic rolls it back, and --wait with "
        "--timeout turn a hang or an early success into an explicit result.",
        "Use helm upgrade --install --atomic --wait --timeout 10m (Helm 4: --rollback-on-failure).",
        70,
        58,
    ),
    # ---- Test quality -----------------------------------------------------------------------
    "TH001": _r(
        "medium",
        "Spoofing: identity is unconfirmed across a trust boundary",
        "The receiving component may accept an unauthenticated identity.",
        "Verify how the receiver authenticates callers and rejects invalid credentials.",
        35,
    ),
    "TH002": _r(
        "medium",
        "Tampering: integrity protection is unconfirmed",
        "Data that crosses a boundary or writes state may be altered without detection.",
        "Verify transport or message integrity and validate input before accepting writes.",
        35,
    ),
    "TH003": _r(
        "medium",
        "Repudiation: write audit logging is unconfirmed",
        "Missing audit evidence makes it hard to associate state changes with an actor.",
        "Record the actor, timestamp, operation and outcome in a protected audit log.",
        35,
    ),
    "TH004": _r(
        "high",
        "Information disclosure: encryption is unconfirmed",
        "Sensitive or cross-boundary traffic may be exposed in transit.",
        "Verify encrypted transport and endpoint identity for the declared flow.",
        35,
    ),
    "TH005": _r(
        "medium",
        "Denial of service: request limits are unconfirmed",
        "An upstream caller may exhaust a downstream component's capacity.",
        "Verify rate, size or concurrency limits and observe saturation behavior.",
        35,
    ),
    "TH006": _r(
        "high",
        "Elevation of privilege: authorization is unconfirmed",
        "A caller may reach operations outside its role or authority.",
        "Verify the receiving service enforces least-privilege authorization per operation.",
        35,
    ),
    "CODE001": _r(
        "medium", "Mutable Python default argument",
        "The same object is reused across calls and can carry state into unrelated requests.",
        "Use None as the default and create a fresh collection inside the function.", 4,
    ),
    "CODE002": _r(
        "medium", "Bare exception handler silently discards errors",
        "The handler hides unexpected failures and may suppress termination signals.",
        "Catch an expected exception and handle it explicitly, or let it propagate.", 4,
    ),
    "CODE003": _r(
        "medium", "Identity comparison with a value literal",
        "The condition depends on object identity rather than value equality.",
        "Use == or != for string and number values.", 4,
    ),
    "CODE004": _r(
        "medium", "Duplicate literal dictionary key",
        "A later entry silently overwrites the earlier value.",
        "Remove the duplicate or give the entries distinct keys.", 4,
    ),
    "CODE005": _r(
        "medium", "Return from a finally block",
        "The return can suppress an exception or replace a previously computed result.",
        "Keep cleanup in finally and return after the try statement.", 4,
    ),
    "TEST001": _r(
        "medium",
        "Test asserts nothing",
        "A test that cannot fail passes forever and gives false confidence; this is the main "
        "danger of generated tests.",
        "Assert on behaviour, or mark a deliberate smoke test with `# radea: allow-no-assert`. "
        "Measure real strength with mutation testing.",
        3,
        46,
    ),
    "TEST002": _r(
        "medium",
        "Assertion is always true",
        "assert True, comparing a value with itself or similar assertions can never fail.",
        "Compare the result with an independently known expected value.",
        3,
        40,
    ),
    "TEST003": _r(
        "low",
        "Test body is empty",
        "A placeholder passes and counts as coverage without testing anything.",
        "Implement it, or delete it, or skip it with a reason.",
        3,
    ),
    "TEST004": _r(
        "medium",
        "Test swallows failures",
        "An empty except/catch of a broad exception turns a real failure into a pass.",
        "Let the exception fail the test, or assert the specific exception expected.",
        3,
        40,
    ),
    # ---- Right-sizing -----------------------------------------------------------------------
    "RS001": _r(
        "medium",
        "CPU request is below observed p95 usage",
        "The scheduler packs the pod as if it needed less than it does; neighbours then cause "
        "throttling under load.",
        "Raise the CPU request to the recommended value, validate in staging, then roll out.",
        14,
        77,
        78,
    ),
    "RS002": _r(
        "high",
        "Memory request is below observed p99 usage",
        "Pods using more than they requested are first in line for eviction under node pressure.",
        "Raise the memory request to cover p99 with headroom.",
        14,
        78,
    ),
    "RS003": _r(
        "high",
        "Memory limit is too close to observed peak",
        "Memory over the limit is an OOMKill, not throttling; a peak near the limit will hit it.",
        "Set the memory limit comfortably above the observed maximum.",
        14,
        78,
    ),
    "RS004": _r(
        "low",
        "Request is far above what the workload uses",
        "Over-provisioning wastes node capacity and money and slows scheduling.",
        "Lower the request towards the recommendation once p95/p99 are confirmed over time.",
        14,
        17,
        78,
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
