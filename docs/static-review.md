# Deterministic reviews

RADEA's analysis commands (`debug`, `iac-review`, `triage`) read logs and may use a model. The
commands in the table read files, apply fixed rules and print the same result every time.
No model, no network, no cluster or cloud credentials, no GPU. Every finding comes from a rule
in the [rule reference](rules.md) with its severity, the reason, the fix and the article it
implements.

| Command | Reads | Looks for |
| --- | --- | --- |
| `k8s-review PATH...` | Rendered manifests, Helm chart sources, Argo Rollouts and Flagger canaries | Probes, image pinning, requests/limits, security context, rollout strategy, replicas and PDBs, selectors, HPA/VPA conflicts, RBAC, secrets, Service selectors, canary and blue-green safeguards, chart hygiene |
| `dockerfile-review PATH...` | `Dockerfile`, `Dockerfile.*`, `*.dockerfile` | Mutable tags, root user, baked-in secrets, remote scripts, cache and layer hygiene, build tools in the final image |
| `ci-review PATH...` | GitHub Actions workflows, GitLab CI files | Unpinned actions/includes, privileged triggers, script injection, curl-to-shell, printed secrets, ignored security failures, floating image tags, `helm upgrade` without `--atomic`/`--timeout` |
| `tf-review PATH...` | Terraform `.tf` files | World-open ingress, literal secrets, disabled encryption, public exposure, unpinned providers and modules, missing destroy guards |
| `vuln-triage REPORT...` | Grype or Trivy JSON | Groups by package, ranks by severity and fix availability, counts what is hidden |
| `test-review PATH...` | Python, Java and Kotlin test files | Tests with no assertion, always-true assertions, empty bodies, swallowed failures |
| `flaky JUNIT...` | Several JUnit XML runs | Tests that both pass and fail (flaky) versus tests that always fail (broken) |
| `rightsize USAGE...` | JSON of observed p95/p99 usage | Requests and limits that disagree with usage, with recommended values |
| `changelog` | A git range | Technical changelog, release-note draft and a commit-hygiene report |
| `policy-check --plan` | `terraform show -json` | Destructive plan actions (blocking gate, existing command) |
| `rules` | Nothing | Lists every rule |

## Exit codes and gating

`k8s-review`, `dockerfile-review`, `ci-review`, `tf-review`, `test-review`, `vuln-triage`,
`flaky` and `rightsize` share one contract, the same as `policy-check`:

| Exit | Meaning |
| --- | --- |
| 0 | No finding at or above `--fail-on` |
| 2 | At least one finding at or above `--fail-on` (default `high`) |
| 1 | Invalid input, unreadable file, or nothing to review |

`--fail-on high|medium|low|never` selects the threshold. `--output json` prints the full
report (`schema_version`, `summary`, `findings`, `sources`, `skipped`, `limitations`); each
finding carries `rule`, `severity`, `target`, `path`, `line`, a sanitized `evidence` quote,
`why`, `fix` and `articles`. Files that could not be reviewed are listed under `skipped` with
a reason, never ignored silently.

## Validate a CRD against Kubernetes

```sh
radea crd-validate examples/k8s-operator/crd.yaml \
  --kubeconfig /path/to/lab.kubeconfig --context lab
```

`crd-validate` sends one `apiextensions.k8s.io/v1` CRD to the selected API server
using strict validation and server-side dry-run. The server applies its normal API
and admission checks without persisting the CRD. The caller needs the permissions
required for server-side apply. Exit 0 means kubectl accepted the dry-run, exit 2
means kubectl could not complete it successfully, and exit 1 means RADEA could not
prepare the request or run kubectl. The JSON report includes a bounded, redacted
diagnostic. Test any conversion webhook and existing custom resources separately.

## Using them in a pipeline

```sh
# GitLab CI or any shell: fail the job on high-severity findings
radea ci-review .gitlab-ci.yml .github/workflows
radea dockerfile-review .
radea tf-review infra/
helm template ./chart | radea k8s-review -          # render first; `-` reads stdin
trivy image --format json app:1.2.3 > scan.json && radea vuln-triage scan.json
radea flaky build/test-results/run-*.xml --fail-on medium
radea changelog --from v1.4.0 > CHANGELOG.draft.md  # a human approves it before release
```

Install the same locked, hash-verified dependencies as the rest of RADEA; PyYAML is the only
addition and is used with `safe_load` semantics only.

## What they deliberately do not do

* They do not execute anything, apply changes or contact a cluster, registry or cloud API.
* Helm templates are not rendered; chart sources get chart-level checks only.
* Variables, locals and module outputs in Terraform are not evaluated, so values built from
  them are not seen. The Terraform reader is tolerant, not a full HCL parser.
* Scanner severities and fix versions are taken as given; reachability is not assessed.
* A clean result is not a proof of safety. Treat these as a fast, repeatable first gate.

## Input safety

Files are read with `RADEA_MAX_INPUT_BYTES` (default 8 MiB), at most 500 per run, and symlinks
met while walking a directory are not followed. YAML is loaded with a safe loader, custom tags
become plain data and aliases are counted once, so an alias bomb cannot blow up memory. XML
that declares a DOCTYPE or entities is rejected before parsing. Git refs for `changelog` are
validated and cannot be options. All text shown is passed through the sanitizer and secret
values (environment values, Secret data, Terraform attributes) are never echoed.

## Resource use

Measured on a laptop-class CPU, no GPU, no network: start-up 0.08 s and 17 MB; 2,000
Deployments (3.4 MB of YAML) in 2.2 s and 59 MB; a 5,000-resource Terraform file in 0.6 s
and 34 MB; a 3 MB build log in 3 s and 29 MB. Regular expressions are bounded and every
adversarial 64 KiB line sanitizes in about a second or less (regression-tested).

## Rendered manifest diff and Kubernetes lab

```bash
helm template radea-lab examples/k8s-lab > before.yaml
helm template radea-lab examples/k8s-lab --set replicaCount=3 > after.yaml
radea manifest-diff before.yaml after.yaml --output json --fail-on-change
```

`manifest-diff` matches named objects by API group, kind, namespace and name. It ignores YAML
comments, mapping order and document order. List order and API version changes remain visible.
The report includes object identities and changed top-level field names. Field values are kept
out of the report. Server defaults, admission, API conversions and schema-specific list semantics
require separate cluster verification. Omitted namespaces remain distinct from explicit ones.
Use one file per side, with `-` accepted for one side. Each stream accepts named resources
and rejects YAML merge keys, duplicate keys and custom tags. Exit 1 indicates invalid input, and
`--fail-on-change` returns 2 when differences exist.

`tools/k8s_lab.sh` runs the offline Helm and RADEA checks. It rejects a zero-replica
override through the chart's schema and compares two valid renders. With `--minikube` it also
creates a disposable profile with its own kubeconfig, installs the chart, tests the Service
from a pod, upgrades, tests again, rolls back and verifies the original replica count. The
test image must be pullable by the cluster and the machine must have a working Minikube driver.
When kubectl is available, the static lab also verifies that a Helm values override and a
Kustomize replicas overlay render equivalent resources.

### Source to Pod

Run `tools/k8s_lab.sh --source-to-pod` with a working Minikube driver. The lab
generates a Python service, runs its unit tests and gates the Dockerfile review
before building an image in the isolated node's runtime. The base image is pinned
by digest and must be pullable from Docker Hub. The lab deploys the built image
with `preview-env`, waits for readiness, checks the HTTP status and JSON through
the in-cluster Service, then waits for namespace deletion. The image stays local
to the disposable cluster. Registry publishing, scanning and signing are separate
pipeline stages.

### Application smoke checks

Save up to ten GET assertions in a JSON file. Each case has a normalized `path` and
the expected HTTP `status`. Add `json` to compare the entire JSON response.

```json
[
  {"path": "/healthz", "status": 200, "json": {"status": "ok"}},
  {"path": "/synthetic-degraded", "status": 503}
]
```

```sh
radea k8s-smoke smoke.json --kubeconfig lab.kubeconfig --context lab \
  --namespace staging --deployment app --origin http://127.0.0.1:8080
```

Supply an origin that reaches the selected application, such as a port-forward
to its Service. The command waits up to 12 seconds for the Deployment rollout
before sending requests. Exit 1 indicates input or rollout failure, and exit 2
indicates an HTTP assertion or transport failure. Reports identify failing cases
by input order and include status codes without response bodies. The application
or test environment must produce any degraded state being asserted.

### Helm release and operator scenarios

The cluster lab installs a preview release and tests it over a separate Service. It then
exposes both releases through the active Service and checks that both return the expected
HTTP body before promoting preview. Four stable replicas and one preview replica provide
a small share of endpoints. Kubernetes Service routing can vary by connection and does
not enforce an exact HTTP request percentage. The lab verifies return to the stable
Service selector with repeated HTTP requests.

The lab also applies the Message CRD from `examples/k8s-operator` and verifies server-side
schema rejection. The sample namespaced controller projects the Message into an owned
ConfigMap and records the observed generation on the status subresource. The lab verifies
external drift repair, spec updates, and cascading cleanup. For repeated reconciliation,
run `tools/k8s_message_controller.py` with an explicit kubeconfig, context and namespace.

Run `tools/k8s_lab.sh --operator` to build the controller image and deploy it with
the ServiceAccount and namespaced Role in `examples/k8s-operator/controller.yaml`.
The Pod builds a temporary kubeconfig that references its mounted token and CA.
The lab checks that the controller cannot read Secrets or create ConfigMaps in
another namespace. It observes Message status, manually changes the owned
ConfigMap, verifies automatic repair, then deletes the Message and waits for
garbage collection. The controller example uses one replica and polls its namespace.
The example uses polling and optimistic concurrency. Use a lab context with permissions
for Message list and status patch, and for ConfigMap get, create, and update.

## CI dependency graphs and migration drafts

```bash
radea ci-graph .gitlab-ci.yml
radea ci-translate .gitlab-ci.yml > candidate.yml
radea ci-diff .gitlab-ci.yml candidate.yml --fail-on-change
radea ci-review candidate.yml
```

`ci-graph` reports jobs, explicit dependencies, optional dependencies, implicit GitLab
stage barriers and one valid local ordering. Cycles are input errors. Use `--platform` when
auto-detection is ambiguous. `ci-diff` matches jobs by identifier and compares their
dependencies. Its gate exits 2 on changed or unresolved topology. Includes, inheritance,
cross-pipeline dependencies and conditional jobs may make the graph partial. Both commands
inspect a single YAML file per input and leave scripts, artifacts and runtime behavior to
separate checks.

`ci-translate` supports GitLab files containing local jobs with a literal list of shell
commands, optional `stage` and literal local `needs`. It rejects other job keys and
known GitLab or GitHub expressions inside scripts. The output is JSON in YAML-compatible
syntax for a manual GitHub Actions workflow with read-only checkout permissions, an Ubuntu
runner and a 30-minute job timeout. The output contains the source shell commands, so keep
the candidate private if the input is private. Review runner tools, checkout behavior, scripts
and defaults before running the workflow.

For the reverse direction, run `radea ci-translate workflow.yml --from-platform github
--image IMAGE@sha256:DIGEST`. The source subset uses Ubuntu jobs with the same pinned
checkout as the forward translator, one explicit Bash step and local dependencies.
The GitLab draft runs only when started through the web UI. It uses the supplied
image, preserves dependency edges and disables implicit downloads between jobs.
Run `ci-diff` on the draft to verify topology. Validate runner tools, checkout credentials
and application behavior on the destination platform before cutover.
[GitLab dependency syntax](https://docs.gitlab.com/ci/yaml/#needs)

## Kubernetes health and drift snapshots

```bash
kubectl --context YOUR_CONTEXT -n YOUR_NAMESPACE get pods -o json > pods.json
radea k8s-health pods.json --fail-on-signal
kubectl --context YOUR_CONTEXT get -f desired.yaml -o json > observed.json
radea k8s-drift desired.yaml observed.json --fail-on-drift
```

`k8s-health` summarizes Pod phase, restart counts and recognized conditions and container
states. It reads Pod, PodList or List JSON and returns concrete follow-up checks. Message
bodies and container logs are excluded from output. The gate returns 2 on recognized signals.

`k8s-drift` reads named YAML/JSON objects or a Kubernetes List. It compares explicitly
declared fields, ignoring status and extra keys added to live mappings. It also reports
missing and unexpected objects. Include namespaces explicitly and scope both snapshots
to the same resources. List order and length are compared, so admission-injected
containers and ordered list changes can appear as drift. Use `--fail-on-drift` to return 2
on any difference. The command operates on files and leaves the cluster unchanged.

## Terraform refresh drift

`radea tf-drift plan.json --fail-on-drift` reads `resource_drift` from `terraform show -json`
output. It reports resource addresses and refresh actions without printing attribute values.
Planned changes remain available through `radea policy-check`. The gate returns 2 for
reported drift and incomplete plans. Generate a plan with refresh enabled to detect
out-of-band changes.

## Rolling metric and cost anomaly checks

```json
{"series":{"request_errors":{"history":[3,4,3,5,4,3,4,3,4,5],"current":25}}}
```

Run `radea metric-anomalies series.json --fail-on-anomaly`. Supply readings from oldest
to newest with a consistent unit and sampling interval. The baseline uses the most recent
`--window` historical readings. An anomaly exceeds both the scaled median absolute
deviation threshold and a relative floor based on the median. A flat zero baseline flags
any nonzero reading. The report exposes the limit and observed deviation to support
review before wiring the check to an alert or CI gate.

To collect the readings from Prometheus, save a query per metric in `queries.json`:

```json
{"queries":{"request_errors":"sum(rate(http_requests_total{status=~\"5..\"}[5m]))"}}
```

Run `radea metric-anomalies queries.json --prometheus http://127.0.0.1:9090 --step 60 --watch 60`.
Each query must yield one complete, finite series at the given interval. The latest
aligned sample is compared with the preceding `--window` samples. Prometheus mode
accepts up to ten queries and 1,000 historical samples per query. Missing or ambiguous
data produces an input error, and watch mode keeps the last valid alert state.

## STRIDE threat-model draft

```json
{
  "components":[{"id":"client","zone":"outside"},{"id":"api","zone":"app"}],
  "flows":[{"id":"submit","from":"client","to":"api","writes":true,
            "sensitive":true,"controls":{"authenticated":true,"encrypted":true}}]
}
```

Run `radea threat-review model.json --output json`. Components belong to named trust
zones. Flows identify endpoints and can declare `writes` and `sensitive`. The controls are
`authenticated`, `integrity_protected`, `audit_logged`, `encrypted`, `rate_limited` and
`authorized`. Use booleans to record verified controls and omit controls that still need
review. The report applies the published STRIDE rules, points to each flow, and marks
the analysis as a draft. Use abstract component and flow labels.

Save the JSON draft and its SHA-256, then run
`radea threat-disposition draft.json decisions.json --require-complete`.
The decisions file contains `draft_sha256` and a `decisions` array. Each entry
identifies a finding by `rule` and `target` and supplies an `owner`, `reason`,
and `status` of `accept`, `mitigate`, `monitor`, or `dismiss`. The gate
returns exit 2 while findings are pending. Rerender and review the draft when
the model changes. Owners evaluate plausibility and verify deployed controls.

## Local GitOps and runtime flags

The Minikube lab creates a temporary Git repository with the desired ConfigMap. It applies
the manifest directly from a commit, checks for drift after a manual edit, and applies the
committed version again to restore the declared state. The final rollback is a Git revert
followed by reconciliation. The example uses a dedicated field manager and forces ownership
conflicts only for the disposable lab ConfigMap.

The demo workload mounts the ConfigMap as a directory and reads the flag file for
each request. The lab waits for Kubernetes to refresh the projected volume and verifies
the response changed without advancing the Deployment generation. After the Git revert,
the endpoint again serves the original flag. Use the Pod-template annotation
`radea.dev/reloadable-config-volumes` to list verified hot-read volumes for K8S031.
ConfigMap or Secret environment variables and mounts with `subPath` still need a rollout.

## OpenTelemetry capture review

```bash
radea telemetry-review traces.jsonl --logs logs.jsonl --metrics metrics.jsonl
```

Use local OTLP/JSON or OTLP JSON Lines files. The command correlates captured spans, log
records and metric exemplars by trace ID. It reports span errors, error logs, missing
parent spans, unmatched log and exemplar counts, and the observed span window. The
window spans the earliest captured start to the latest captured end. Partial sampling
and clock skew can affect it. Log bodies, span names and attributes are excluded.
The command reads existing files. Configure instrumentation, collection and retention
in the observed system. [OTLP JSON encoding](https://opentelemetry.io/docs/specs/otlp/)
and [file exporter format](https://opentelemetry.io/docs/specs/otel/protocol/file-exporter/).

## Committed Kubernetes bundles

```bash
radea gitops-sync --repo . --ref main --manifest deploy/bundle.yaml   --kubeconfig /path/to/kubeconfig --context my-cluster --namespace app --interval 30
```

Use a multi-document YAML file of v1 ConfigMaps and ClusterIP Services with selectors.
Pass `--allow-deployments` to also apply trusted apps/v1 Deployments.
Every document must explicitly name the target namespace. The command reads the Git blob
at the resolved commit and uses server-side apply. With `--interval`, every iteration
reapplies the bundle to detect and reconcile drift even if the commit is unchanged.
Use `--remote origin --ref refs/heads/main` to fetch a trusted, already configured
remote before applying. A fetch failure aborts that iteration. Protect the remote
branch against unauthorized changes. The default server-side mode preserves resources
removed from Git. Check resource status before retrying a partially applied bundle.

Use `--applyset radea-inventory` to explicitly opt into namespace-scoped pruning
using a cluster-side ConfigMap inventory. This mode moves to kubectl's alpha ApplySet
and client-side apply, supports a nonempty bundle, and cannot use `--force-conflicts`.
Use a dedicated inventory and scoped credentials, especially before enrolling existing
resources. Run `tools/k8s_lab.sh --gitops` to exercise fetch, pruning, Deployment
reconciliation and rollback through Git revert in a disposable namespace.
[Kubernetes ApplySet pruning](https://v1-34.docs.kubernetes.io/docs/tasks/manage-kubernetes-objects/declarative-config/).

## DORA delivery report

`radea dora-report events.json` takes a reporting window with timezone-aware `start` and
`end`, and `deployments`. Each event describes a production deployment with `id`,
`service`, `deployed_at`, and boolean `failed` and `rework` classifications. A failed
deployment may have `recovered_at`. Optional `changes` entries contain an `id` and
`committed_at`. Include earlier deployment history to avoid counting redeployments as
new changes. The per-service report gives five delivery metrics, counts incomplete
recovery samples separately and uses a half-open reporting window. Collection and
classification are supplied by the caller. [DORA metric definitions](https://dora.dev/guides/dora-metrics/).

## CycloneDX and vulnerability findings

`radea sbom-review bom.json scan.json` joins CycloneDX JSON to Grype or Trivy JSON. It matches
by exact package URL when the scanner provides one, otherwise uses an unambiguous name and
version. For a known application root, dependency depth counts edges in the declared graph.
Missing paths remain unknown, and a path in an SBOM cannot establish whether vulnerable code
executes. [CycloneDX software dependencies](https://cyclonedx.org/use-cases/software-dependencies/).

Pass `--runtime runtime.json` to correlate external execution evidence. The JSON
contains `bom_sha256` for the exact inventory and an `observations` array of
`{"bom_ref":"lib@1","id":"CVE-2025-0000","symbol":"package.function"}` entries.
Supply observations only when your trace and vulnerability advisory establish
the symbol mapping. The report counts unique observed symbols on unambiguous
matches, omits symbol names and preserves every scanner finding. Absent and
unmatched observations leave runtime reachability unknown.

## Compare Terraform resource plans

Generate two comparable plans, then export them with `terraform show -json`.
Run `radea tf-plan-diff baseline.json candidate.json --fail-on-change` to compare
resource addresses, actions, planned values, sensitivity, and move/import metadata.
The report identifies changed resources and counts changed top-level attributes.
Attribute names and values stay out of the report. Unknown values and deferred
changes make the gate fail closed. Review Terraform outputs, provider behavior,
and policy gates as part of the normal deployment review.

## Rebuild parity

Capture the same inventory before and after rebuilding from IaC. Use JSON
objects keyed by package, service, config file, or probe identifier:

```json
{"packages":{"example":"1.2.3"},"services":{"example.service":"enabled,active"},
 "config_sha256":{},"probes":{"GET /healthz":"200"}}
```

Populate `config_sha256` with hashes of selected stable configuration files.
Capture package versions and service states with your host's inventory tools,
and run application probes from the same vantage point after each build.
`radea rebuild-check original.json rebuilt.json --fail-on-change` reports missing,
new and modified entries without printing values, and treats a missing category
on either side as incomplete. Select the same scope for both captures and keep
secrets in their source systems.

## Cross-repository contract check

Give each repository or monorepo module a JSON manifest, such as
`{"repository":"api","provides":{"checkout/http":"v2"}}` and
`{"repository":"client","requires":{"checkout/http":"v2"}}`.
Run `radea repo-contract-check api.json client.json --fail-on-change`.
Each contract has one provider and can have multiple consumers. Missing providers
and unequal revisions trigger exit 2 with the gate enabled. Generate the manifests
from the revisions under review. Teams define revision identifiers and validate
interface behavior with their own contract tests.

## Secret migration readiness

Run `radea secret-migration-plan inventory.json --require-ready` to track migration
without supplying secret values. The JSON contains a `secrets` array. Each record
declares an `id`, `owner`, and unique `consumers`. Add the target manager
`reference`, the `verified_consumers` list, and the boolean records
`rotation_verified`, `legacy_removed`, and `plaintext_scan_clean` after completing
those steps. The gate reports outstanding steps and exits 2 while they remain.
The workflow relies on the team's verification and keeps secret material in the manager.

## Dependency approval gate

Run `radea dependency-review approved.json proposed.json --fail-on-unapproved`
before installation. Both inventories have a `dependencies` array with canonical,
versioned `purl`, HTTPS `registry`, and lowercase `sha256` fields. Export resolved
artifact metadata without installing packages and review approvals through a trusted
channel. The gate reports unapproved coordinates, changed registry origins and
changed hashes. It uses the supplied snapshots and performs no network lookups.

## IAM simulation expectations

Save AWS IAM simulator JSON for the principal and context under review. In
`cases.json`, list objects with `action`, `resource`, and `expect` set to
`allow` or `deny`. Run `radea iam-simulation-review export.json cases.json
--fail-on-mismatch`. RADEA uses resource-specific decisions where available.
Missing results or missing context fail the gate as unknown. The report shows
case numbers and decisions without repeating resource ARNs or context values.
Live authorization can differ from the simulator. [AWS IAM policy simulator](https://docs.aws.amazon.com/IAM/latest/UserGuide/access_policies_testing-policies.html)

## Kubernetes resource access

`radea rbac-access rbac.yaml --user system:serviceaccount:app:reader --namespace app
--verb get --resource pods/status --resource-name example` evaluates the resource
request against a YAML snapshot. Include all relevant Role, ClusterRole, RoleBinding and
ClusterRoleBinding objects. Supply authenticated groups with repeated `--group` options.
The report identifies the bindings that grant access, distinguishes an unresolved role
from a missing grant, and leaves other authorizers and admission out of the decision.
Use a current authorization review against the cluster for enforcement decisions.
[Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/).

## Local metric alerts

`radea metric-anomalies series.json --watch 15` reads an updated file every 15 seconds.
It writes one JSON line when a metric opens or recovers. Input errors are written to stderr
and polling continues with the previous alert states intact. Update the series file by
atomic replacement. The watcher uses in-memory state and stdout for alert delivery.

## Observe CI log snapshots

Run `radea ci-observe logs/ --threshold 3` for counts of lines matching the
offline CI signature categories. Directories contribute `.log` files and
explicit files may use other extensions. Pass `--watch 30` to poll rolling
snapshots and print JSON opening and recovery events to stdout. Replace logs
atomically and keep each snapshot within the input and line limits.
Incomplete snapshots preserve the previous alert state. Counts describe
matched lines and the report omits log text. Route events to your alerting system.

## Compare shadow CI runs

Run the baseline and candidate pipelines against the same commit, collect one JUnit
report from each, and pass them to `radea ci-shadow baseline.xml candidate.xml`.
Matching uses the JUnit class and test name. The command reports changed, missing,
and added test outcomes. `--fail-on-change` returns exit 2 for any difference.
Ensure test identifiers are unique after merging parallel shards. The comparison
uses the supplied artifacts. Your CI platform schedules the two runs.

For artifact and timing comparisons, supply `--baseline-build before.json` and
`--candidate-build after.json`. Each job records the full Git `revision`, its
`duration_ms`, and an `artifacts` object mapping logical artifact names to
lowercase SHA-256 digests calculated from the finished files. The command
rejects mismatched revisions, reports added, removed and changed artifacts, and
shows the elapsed-time delta. Artifact differences also trigger `--fail-on-change`.
Use consistent job boundaries when measuring time.

## Attribute billed cloud costs

`radea cost-report focus.csv --by ServiceName --tag team` groups a local FOCUS CSV
export by the selected dimension and tag. The command validates `BilledCost` and
`BillingCurrency`, uses exact decimal arithmetic, and reports each currency separately.
The optional `Tags` column must contain JSON objects. Absent dimensions remain null
and count as unattributed rows. Choose the billing period when exporting the data.
[FOCUS BilledCost](https://focus.finops.org/docs/specification/v1-4/columns/cost-and-usage/billed-cost/)
and [BillingCurrency](https://focus.finops.org/docs/specification/v1-3/columns/cost-and-usage/billing-currency/).

For a before-and-after review, run
`radea cost-report after.csv --baseline before.csv --by ServiceName --tag team`.
Use comparable periods and export filters. The report compares matching currency
and dimension groups with exact decimal deltas. Missing groups appear as null
on the corresponding side so additions and removals remain visible.

## Digest admission policy in Minikube

Run `tools/k8s_lab.sh --admission` to start a disposable profile and exercise the
Kubernetes ValidatingAdmissionPolicy in `examples/k8s-admission`. The binding matches
a dedicated namespace label. Server-side dry runs verify that a tag-only Pod is denied,
a digest-shaped reference is accepted, and the tag-only Pod is still admitted in a
namespace outside the binding. Signature verification requires a separate verifier.
[Kubernetes ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/).

## Canary promotion decision

`radea canary-gate measurements.json --max-p95-ms 200` accepts
`{"requests":[{"ok":true,"latency_ms":100},{"ok":false}]}` for observations of the
candidate only. Failed requests count against success rate. The p95 uses nearest rank
over successful request latencies. The gate returns 0 for promotion, 2 for rollback,
3 to wait for the minimum sample count, and 1 on invalid input. Collect a representative
window before evaluation. Wire these exit states to the rollout controller's supported
promotion, abort and pause actions.

`tools/k8s_lab.sh --canary` exercises the gate in a disposable Minikube profile.
The lab samples the preview Service from a Pod and checks the expected response
body. It sends a deliberately failing path to exercise rollback, then a healthy
path to exercise promotion. After each decision it verifies the active Service
over HTTP. The sample latency includes kubectl exec overhead. The lab uses
replica-backed Service selectors, so exact per-request weights and service
telemetry require an ingress or mesh integration.

## Python mutation testing

`radea mutation-test module.py test_module.py --fail-on-survival` runs a baseline and one
temporary module copy per mutation. The runner requires pytest in the RADEA environment.
The selected test file must import the selected module by filename without relying on
other project files, pytest plugins, or conftest files. Comparisons and boolean literals
are mutated one at a time. A passing mutant survives, an assertion failure kills it,
and runner failures or timeouts are inconclusive. User tests execute with the local
process permissions. Use trusted tests and code. The gate also fails if the mutation
limit prevents full evaluation of the supported variants.

## Python code review

Run `radea code-review src --output json` for local checks with source lines.
The supported rules flag mutable default arguments, silent bare exception handlers,
identity comparisons against value literals, duplicate literal dictionary keys and
direct returns in `finally` blocks. Results are advisory by default.
Use `--fail-on medium` to enable a gate. Run the normal formatter, project tests,
and human review alongside these mechanical checks.

For patch review, pass `radea code-review edited.py --baseline original.py --output json`.
The report identifies the baseline file and limits findings to changed candidate lines.
This mode supports one file pair of up to 5,000 lines each.

## Platform documentation and service starter

`radea docs-answer "How do Helm rollbacks work?" docs` returns matching excerpts with file
paths and line ranges. It uses local lexical retrieval and returns `no_documented_answer`
when it finds too little matching terminology. It limits and redacts excerpts before output.
Pass `--gap-log gaps.jsonl --topic deployment` to count unanswered requests under a
chosen category. `radea docs-backlog gaps.jsonl` ranks those categories. The log
contains category names only.

`radea service-scaffold ./my-service --name my-service --base-image <python-image>@sha256:<digest>`
creates a new directory containing a Python health endpoint, unit tests, a Dockerfile with
a non-root user, and a pinned, read-only GitHub Actions workflow. Use a Python base image
that your platform approves. The command writes local files for human review.
Pass `--owner platform-team` to add an experimental Backstage service descriptor
with the named group as owner. Register the generated descriptor through your
platform's existing catalog ingestion process.
[Backstage component descriptor](https://backstage.io/docs/features/software-catalog/descriptor-format/#kind-component)

## Preview incremental migration routing

`radea migration-route plan.json --path /billing/invoices --cohort synthetic-123`
reads a plan such as `{"routes":[{"prefix":"/billing","candidate_percent":10}]}`.
It chooses the most specific path prefix and deterministically assigns a stable
cohort to legacy or candidate. A zero percentage restores all traffic decisions
for that prefix to legacy. Unlisted paths default to legacy. The command returns
a decision for testing a migration plan.

`radea migration-serve plan.json --legacy-port 8001 --candidate-port 8002 --port 8080`
serves the same rules at `127.0.0.1:8080`. Send `X-RADEA-Cohort` on a GET or HEAD
request to select a stable bucket. Requests without that header go to legacy.
A weight of 25 assigns 25 of 100 buckets to the candidate. Observed request
fractions depend on the caller population and whether cohorts make repeated requests.
Replace the rules file atomically to change the weight without restarting the facade.

Both upstreams must be on IPv4 loopback. The facade forwards the path and method,
without forwarding client credentials or cookies. It returns 502 if the chosen
upstream is unreachable or sends an unsupported redirect, encoding, or oversized
response. It supports bounded, normalized paths without query strings and is
intended for local HTTP rehearsals.

## CI feedback timing

`radea ci-timing timings.json` compares `baseline` and `candidate` arrays of runs.
Each run has `duration_seconds`, optional `diagnosed_seconds`, and `jobs`. Job
records carry `started_seconds` and `finished_seconds` relative to run start, an
`outcome` (pass, fail, skip or cancel), and optional `cache` (hit, miss or unknown).
The report includes median wall-clock time, earliest completed failing job,
time to diagnosis, peak overlapping jobs and measured cache hit rates.
It reports sample sizes and uses null when a signal or cache observation is absent.

## Helm render matrix

`radea helm-matrix ./old ./new --values staging=stage.yaml --values prod=common.yaml
--values prod=prod.yaml --fail-on-change` renders both chart directories locally.
Repeat a name to layer additional values in command order. Helm validates its own
schema and RADEA reports resource-level changes with field names, omitting values.
Use `--fail-on-change` to return exit 2 if any environment differs.
[Helm template reference](https://helm.sh/docs/helm/helm_template/).

When refactoring a values schema, pass separate files for the affected sides:

```sh
radea helm-matrix ./old ./new --before-values prod=legacy.yaml \
  --after-values prod=refactored.yaml --fail-on-change
```

Helm applies shared layers first, then baseline-only or candidate-only layers
in their respective order. Include every deployment environment in the matrix.

## Offline image signature verification

`radea image-verify manifest.json payload.json signature.b64 --key signer.pem
--repository registry.example.org/team/app` checks a detached SHA-256 RSA or ECDSA
signature over the exact simple-signing payload using OpenSSL. It checks the payload
type and repository and compares the signed digest with the exact local manifest bytes.
Select the signer public key through a trusted channel. Pass
`--admission-namespace radea-admission` to emit an allowlist ConfigMap only after
verification succeeds. The [example admission binding](../examples/k8s-admission/verified-images.yaml)
compares exact digest references against that inventory. Restrict writes to the
ConfigMap to the trusted verification pipeline. Run `tools/k8s_lab.sh --admission`
for the dry-run checks with a synthetic manifest and signature. Keyless identity
and transparency-log verification require separate integration.
[Cosign signing claims](https://docs.sigstore.dev/cosign/system_config/specifications/).

## Cutover rehearsal

`radea cutover-plan plan.json --fail-at switch` validates a runbook and emits a
draft with simulated forward and reverse events. Provide a `name` and a `steps`
array. Each step has a unique `id`, an `owner`, and textual `apply`, `verify`,
`rollback` and `verify_rollback` fields. A failed verification rolls back the failed
step and the earlier applied steps, in reverse order. The rehearsal validates sequencing
and requires staging verification of the underlying operations.

## Shell modernization checks

`radea shell-review candidate.sh --baseline original.sh --fail-on-new` uses a local
ShellCheck binary. It compares the counts of diagnostics by level, rule and message,
so line movements alone do not register as new. Use `--shell bash` for scripts without a
shebang. Exit 2 means new findings. The command analyzes source without executing it.
Behavioral parity still requires tests for the intended inputs and side effects.

## Kubernetes diagnostics and controller selection

`radea k8s-capture POD --kubeconfig PATH --context CONTEXT --namespace NAMESPACE`
reads Pod status and events, filtered by the Pod UID. Event descriptions are omitted.
Opt in to bounded, best-effort-redacted logs with `--container NAME` and optionally
`--previous`. A partial response reports unavailable events or logs. Use a trusted
kubeconfig and an identity with read permissions.

For an escalated diagnostic, save the current Pod JSON and run
`radea k8s-debug-plan pod.json --image IMAGE@sha256:DIGEST > patch.json`.
The generated JSON Patch checks the Pod UID and resource version, then appends
a non-root ephemeral container with a fixed `identity`, `resolver`, or `interfaces`
probe. Use a trusted image with the corresponding command. Apply admission
checks first with `kubectl patch pod POD --subresource=ephemeralcontainers
--type=json --patch-file patch.json --dry-run=server` in the selected context.
Adding it to a live Pod requires a separate operator action and the matching
RBAC permission. The workbench keeps the probe's scope within the selected Pod
and the ephemeral container remains recorded until the Pod is removed.

`radea k8s-workload-plan` recommends a Deployment for interchangeable services.
Pass `--stable-identity`, `--per-pod-storage`, `--ordered`, `--per-node`, `--finite`
or `--scheduled` for other requirements. Conflicting workloads require a design
decision. The result is advisory.

## Feature flag cohorts and experiments

`radea flag-evaluate flags.json checkout --cohort demo-42 --group beta` reads a
configuration such as
`{"flags":{"checkout":{"enabled":true,"rollout":30,"groups":["beta"],"variants":{"control":50,"new":50}}}}`.
Disabled or unknown flags are off. Group restrictions apply before the stable rollout
bucket. Enabled callers can receive a deterministic variant, with weights totaling 100.
Applications supply cohort IDs and group membership from trusted identity context.
The application delivers the variant and records outcomes. To review an export, run
`radea flag-experiment observations.json --control control` with one binary outcome per
cohort in a single experiment:

```json
{"experiment":"checkout-v2","observations":[
  {"cohort":"a","variant":"control","success":false},
  {"cohort":"b","variant":"new","success":true}
]}
```

The report shows counts, observed success rates and percentage-point changes
against the control. Identical duplicates count once and conflicting outcomes
or assignments fail validation. Cohort IDs stay in the input. Interpret results
using the experiment design and sample sizes.

## Human review of a postmortem

`radea postmortem-review draft.json review.json` reads a `radea triage --output json`
draft and binds human decisions to the SHA-256 of the exact file. The review contains
`draft_sha256`, `reviewer`, `conclusion`, `cause_status` (`unknown` or
`confirmed_by_reviewer`), `evidence_ids` and `action_items`. A confirmed cause
requires evidence IDs in the draft. Action items include `owner`, `action` and a
`due` date. The named reviewer supplies the judgment. The command validates references
and structure, and records the reviewer declaration.

## Test generation from declared expectations

`radea test-scaffold cases.json --module app --function parse` emits pytest source.
The input takes the form
`{"cases":[{"id":"empty","args":[""],"kwargs":{},"expected":null}]}`.
Review each expected output against the intended behavior. RADEA uses caller-supplied
expectations and never imports or executes the selected module during generation.

## Team prompt library

`radea prompt-prepare library.json context.json --template incident --version 1`
prepares a local draft packet. Each object in the library's `templates` array
declares an `id`, numeric string `version`, `instruction` and `inputs` array.
The context JSON maps exactly those input names to string values. The output
reports source hashes, applies best-effort redaction, and keeps caller-provided
context separate from the instruction. The command makes no provider calls.

## Package mutation testing

`radea mutation-suite . --package src/app --tests tests --fail-on-survival`
copies the Python files from both directories into disposable workspaces. It
runs the selected pytest suite before testing single mutations across the package.
Relative imports and shared Python test fixtures stay available. Tests requiring
additional data files, external pytest plugins or project configuration need a
separate runner. Use trusted test code; it executes with local process permissions.

## Capture local OpenTelemetry correlation data

`radea telemetry-capture ./capture` listens on `127.0.0.1:4318` and creates a new
capture directory. A compatible exporter can use `OTEL_EXPORTER_OTLP_PROTOCOL=http/json`
and `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318`.
The receiver accepts uncompressed JSON requests at `/v1/traces`, `/v1/logs` and
`/v1/metrics`. Each capture retains the allowlisted fields used by `telemetry-review`.
Log bodies, span names, metric values, attributes and headers are excluded.
Input is capped at 1 MiB per request and each output file is bounded by
`RADEA_MAX_INPUT_BYTES`. A full capture requires a new session. This local listener
supports diagnostic correlation. The [Collector example](../examples/telemetry/collector.yaml)
accepts Protobuf and forwards uncompressed JSON to RADEA on port 14318 over Pod loopback.
Run `tools/k8s_lab.sh --telemetry` to exercise the Collector and capture containers
together. Configure cluster-wide collection, durable storage and alerting separately.
[OTLP protocol](https://opentelemetry.io/docs/specs/otlp/) and
[exporter configuration](https://opentelemetry.io/docs/specs/otel/protocol/exporter/).

## PR-scoped Kubernetes previews

```bash
radea preview-env --project example --pr 42 --kubeconfig ./lab-config --context lab up   --image registry.example.com/team/app@sha256:REPLACE_WITH_DIGEST
radea preview-env --project example --pr 42 --kubeconfig ./lab-config --context lab down
```

Use an image that can run as UID 10001 with a read-only root filesystem and serve
`/healthz` over HTTP on port 8080 by default. `up` applies a Deployment and ClusterIP
Service and waits for rollout. Set `--port` or `--health` if the image uses a different
endpoint. The environment is isolated by namespace. `down` requests deletion only
after checking the ownership labels and passing UID and resourceVersion preconditions.
The command reports `absent` when the namespace is already gone.

Run `tools/k8s_lab.sh --preview` to verify two local previews and their cleanup.
Run `radea preview-env [target options] smoke cases.json` for HTTP assertions
against an owned preview through a temporary loopback port-forward.
A trusted GitHub workflow can pass its event file to `radea preview-pr "$GITHUB_EVENT_PATH"
--repository OWNER/REPO --project example --kubeconfig ./lab-config --context lab`.
Pass `--image` for opened, synchronized and reopened PRs. Closed PRs use deletion.
Pass `--smoke cases.json` to test the preview after rollout and fail the job on divergence.
Fork PRs and unrelated actions are ignored. Use the event file from the trusted runner,
serialize actions per project and PR, and resolve the preview image in a trusted build.
The namespace lifecycle requires authorization to create and delete those namespaces.
[Kubernetes DeleteOptions](https://kubernetes.io/docs/reference/kubernetes-api/definitions/delete-options-v1-meta/).

## Preview TTL cleanup

`radea preview-sweep --project demo --kubeconfig ./lab-config --context lab
--older-than-seconds 86400` lists project previews at least one day old.
Age comes from the namespace creation timestamp. Updating the preview leaves its
original creation age intact. `--apply` requests deletion using the UID and resource
version from the inspected snapshot, with a limit of 25 namespaces by default.
Conflicts are reported and are eligible for a later scan. Use `--interval 60` for
continuous polling or schedule the one-shot command in trusted CI. Listing is the
default mode. Test against disposable namespaces with `tools/k8s_lab.sh --preview-ttl`.

### GitHub Actions preview integration

[The reusable workflow](../examples/ci/github-preview.yml) runs a pinned, trusted
RADEA revision with hashed dependencies. Put it under `.github/workflows` in the
repository hosting your reusable workflows. Call it from a job triggered by
`pull_request` events for opened, synchronize, reopened, and closed. Pass the
expected project, context, a trusted image for open PRs, and the named
`preview_kubeconfig` secret. Pass optional trusted JSON through `smoke_cases`.
The sample uses the called job's `preview` environment
and serializes updates per project and PR. Cluster access is scoped to that
environment. Run TTL sweep on a separate timed schedule if desired.
[GitHub reusable workflow and secret semantics](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).


### Validate a Helm chart end to end

Run `radea helm-review ./chart --values common.yaml --values staging.yaml --fail-on high`.
Values are applied in order. The command runs strict Helm lint and renders locally
with chart dependencies already present. Helm checks the values schema and evaluates
`required` and `fail` expressions along the selected render paths. RADEA reviews the
chart sources and rendered Kubernetes objects and reports the usual finding severities.
Use additional values sets to exercise conditional templates.

Run `radea helm-kustomize-diff ./chart ./overlays/staging --values staging.yaml
--fail-on-change` to compare chart and overlay output. Use a trusted overlay with
local bases for an offline comparison. Kustomize can resolve Git references if
the overlay declares them. The comparison operates on rendered resources and does
not apply changes to the cluster.


### Check behavior before replacing a shell script

Run `radea shell-parity old.sh new.sh cases.json --execute` on trusted scripts.
The JSON case file contains an array such as
`[{"id":"spaced-argument","args":["two words"],"stdin":"input"}]`.
Each script runs with the same case in a separate temporary directory.
The report shows differing exit codes or output streams without printing output
contents. Exit code 2 indicates a mismatch. This command executes local code
with your user permissions. Check filesystem effects and external dependencies
with application-specific tests.

### Trace shell file references

Run `radea shell-graph ci/build.sh --root .` with `shfmt` 3.12 installed. It parses
Bash by default and traces explicit relative paths used by `source`, `.`, plain
shell invocations, and direct `./script.sh` calls. Paths are interpreted relative
to the supplied root as the assumed working directory. The graph follows up to
24 repository files and reports file and line evidence, including references
that form cycles. It parses source without running scripts.

Use `--fail-on-partial` for exit 2 when a recognized reference cannot be resolved.
Dynamic paths, PATH lookups, missing targets, references outside the root, and
explicit working directory changes or `eval` mark the report partial. The graph
describes syntactic references, including conditional branches and uncalled
functions. Inspect dispatch through wrappers, aliases or generated commands
separately. [shfmt syntax tree output](https://github.com/mvdan/sh/blob/v3.12.0/cmd/shfmt/shfmt.1.scd)


### Practice Kubernetes readiness

1. Run `radea learn-readiness start > exercise.yaml`.
2. Run `radea learn-readiness check exercise.yaml` and use the failed checks to diagnose the starter.
3. Edit the manifest and check it again. Use `radea learn-readiness hint` for an explanation
   and a question to answer in your own words.

### Resolve local GitLab pipeline includes

Run `radea ci-graph .gitlab-ci.yml --gitlab-root .` from the repository root.
The graph merges nested literal local includes in declaration order and applies
the main file last. Paths in nested includes are relative to the repository
root. After merging, the graph resolves local `extends` chains, including hidden
templates and multiple parents. Later parents override earlier ones for graph
fields such as `needs` and `stage`, and explicit child values take precedence.
Missing parents appear in `unresolved_extends`. Missing parents, unsupported includes
and dynamic job settings keep the graph marked as partial. The graph reads the
repository snapshot on disk without running CI or fetching includes over the network.

Pass `--before-gitlab-root` and/or `--after-gitlab-root` to `ci-diff` to expand
local includes for the corresponding side before comparing effective edges.

[GitLab include merge semantics](https://docs.gitlab.com/ci/yaml/includes/)
· [GitLab inheritance and merge details](https://docs.gitlab.com/ci/yaml/yaml_optimization/#merge-details)
