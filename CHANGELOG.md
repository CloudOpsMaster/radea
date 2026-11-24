# Changelog

## 0.3.0rc2

### Added
- A manual GitHub Actions delivery demo that checks out a sample app, builds an archive,
  serves a temporary preview, measures real HTTP responses and evaluates a RADEA gate.

### Changed
- The offline demo covers 38 scenarios, with focused governance and migration tracks.
- The GitHub Actions summary shows plain-language outcomes before optional JSON details.

## 0.3.0rc1

### Added
- `flag-experiment` compares deduplicated cohort outcomes by variant against a control.
- `cost-report --baseline` shows exact changes by currency, dimension, and optional tag.
- `ci-shadow` compares artifact digests and timings from two runs of the same Git revision.
- `ci-translate --from-platform github` drafts manual GitLab CI for simple Bash jobs.
- `helm-matrix` supports separate values layers for chart refactors that change the values schema.
- `threat-disposition` binds owner decisions and outstanding findings to an exact STRIDE draft.
- `sbom-review --runtime` correlates observed vulnerability symbols with the exact SBOM.
- `dependency-review` gates package coordinates, registries and hashes against approved metadata.
- `secret-migration-plan` tracks reference migration, consumer readiness and recorded rotation checks.
- `code-review --baseline` limits Python findings to changed candidate lines.
- `repo-contract-check` checks declared interface revisions across local repository snapshots.
- The operator lab runs the Message controller as an unprivileged namespaced Deployment
  and verifies scoped access, drift repair and cascading cleanup.
- `tf-plan-diff` compares resource actions and planned state without reporting attribute data.
- `rebuild-check` compares captured packages, services, config hashes, and application probes.
- `service-scaffold --owner` generates a Backstage catalog descriptor for the new service.
- `iam-simulation-review` gates expected permissions against a saved AWS IAM simulation.
- `pilot-report` can calculate cost-adjusted ROI for the measured cohort.
- `ci-observe` aggregates offline log signatures and emits threshold transitions.
- GitOps can opt into Deployment reconciliation and rollback from trusted Git revisions.
- The image admission lab allows verified digest references and rejects unverified digests.
- Preview workflows can run trusted HTTP assertions through an owned Service.
- `k8s-debug-plan` prepares guarded, restricted ephemeral-container diagnostic patches.
- The telemetry lab pairs OpenTelemetry Collector and RADEA capture in one Pod.
- `shell-graph` traces repository-local shell file references with shfmt without running scripts.
- `ci-graph` resolves inherited GitLab dependency fields, and `ci-diff` can expand
  local GitLab includes independently on each side.
- `k8s-smoke` gates configurable HTTP and JSON assertions on Kubernetes Deployment readiness.
- The Minikube source-to-Pod lab tests a generated service, builds its image and verifies
  the deployed application over its Kubernetes Service.
- `crd-validate` checks a CRD against the selected Kubernetes API with server-side dry-run.
- `migration-serve` applies weighted cohort routing to two loopback HTTP backends.
- `preview-sweep` plans or applies project-scoped TTL cleanup with Kubernetes deletion preconditions.
- `preview-env` creates, updates and cleans up PR-scoped Kubernetes previews.
- `telemetry-capture` accepts local OTLP/HTTP JSON and retains only bounded correlation fields.
- `mutation-suite` runs a shared pytest suite against changes across multiple Python modules.
- `gitops-sync` can fetch a configured remote branch and opt into namespace-scoped ApplySet pruning.
- `prompt-prepare` validates a versioned team prompt and preserves a separate redacted context.
- `test-scaffold` generates parametrized pytest cases from supplied inputs and expected outputs.
- `k8s-capture` reads Pod status, UID-scoped events and opt-in bounded logs.
- `k8s-workload-plan` recommends a controller from explicit requirements.
- `flag-evaluate` evaluates targeted percentage rollouts and stable experiment variants.
- `postmortem-review` binds human decisions and action items to an exact triage draft.
- `shell-review` compares baseline and candidate ShellCheck diagnostics without executing scripts.
- `shell-parity` compares trusted scripts across shared argument and stdin cases.
- `helm-matrix` renders two local charts with ordered values layers and reports per-environment diffs.
- `helm-review` runs strict lint, validates values and inspects rendered resources.
- `image-verify` validates a detached simple-signing signature, repository and SHA-256 digest.
- `cutover-plan` validates a reversible runbook and simulates rollback order on failed verification.
- `ci-timing` compares pipeline feedback time, overlapping jobs and measured cache hits.
- The Minikube canary lab exercises promotion and rollback decisions using HTTP probe samples.
- `migration-route` previews staged legacy or candidate routing with stable cohorts and rollback
  through a zero candidate weight.
- Advisory Python `code-review`, local cited `docs-answer`, and `docs-backlog` for unanswered
  topics. A packaged Python `service-scaffold` template adds unit tests, CI, and a digest-pinned base.
- `mutation-test` runs a pytest baseline and individual Python comparison or boolean mutations
  in temporary work directories.
- `canary-gate` returns a rollout decision from measured success rate, p95 latency and sample size.
- `gateway-route` and `gateway-rollout` configure Gateway API route weights and evaluate
  live Prometheus signals to advance, promote or roll back a rollout.
- `migration-parity` checks a read-only path against two origins and reports divergence categories.
- `cutover-rehearse` stages live Gateway traffic, probes availability and verifies restoration.
- `ci-shadow` gates mismatches between baseline and candidate JUnit artifacts.
- `cost-report` attributes billed costs from FOCUS CSV without combining currencies.
- An isolated Minikube admission test enforces digest-shaped image references.
- `rbac-access` evaluates a Kubernetes resource request against a supplied RBAC snapshot.
- `metric-anomalies --prometheus` reads aligned range samples for rolling anomaly alerts.
- Python code review flags duplicate literal dictionary keys and direct returns in finally blocks.
- `metric-anomalies --watch` emits deduplicated opening and recovery events as input changes.
- `gitops-sync` reconciles committed bundles of namespaced ConfigMaps and ClusterIP Services.
- `dora-report` calculates five delivery metrics from production deployment events.
- `sbom-review` matches scanner findings to a CycloneDX inventory and dependency graph.
- GitOps lab reconciles a committed ConfigMap, repairs manual drift, and verifies a feature flag
  update and Git revert through HTTP without a Deployment rollout.
- `telemetry-review` correlates captured OTLP spans, logs and metric exemplars by trace ID.
- `threat-review` drafts defensive STRIDE review items from declared trust boundaries and controls.
- `pilot-report` compares measured baseline time with assisted execution, verification and rework,
  with acceptance and critical-miss counts for the same cases.
- Kubernetes lab scenarios for canary, blue-green and HTTP verification of a traffic switch,
  plus a Helm/Kustomize replica override comparison.
- CRD checks for served/storage versions and the root OpenAPI schema. A Message controller lab
  validates admission, reconciliation, status and cascading cleanup in Minikube.
- `tf-drift` reports captured Terraform refresh drift. `metric-anomalies` evaluates
  metric or cost readings against a robust rolling baseline.
- `ci-graph` and `ci-diff` inspect local GitHub Actions and GitLab dependency topology.
  `ci-translate` drafts a manual GitHub Actions workflow from simple GitLab shell jobs.
- `ci-graph --gitlab-root` expands nested literal local GitLab includes.
- `k8s-health` summarizes captured Pod symptoms and `k8s-drift` compares declared fields
  with captured Kubernetes resources.
- `manifest-diff` compares rendered Kubernetes objects offline and reports changed fields
  without their values. A local Helm lab covers lint, input validation, render and comparison,
  with an optional Minikube install, upgrade, Service check and rollback scenario.
- Deterministic reviews that use no model and no network: `k8s-review` (Kubernetes manifests
  and Helm chart sources), `dockerfile-review`, `ci-review` (GitHub Actions and GitLab CI),
  `tf-review`, `vuln-triage` (Grype/Trivy), `flaky` (JUnit runs), `rightsize`, `changelog`
  and `rules`. 100 rules, each traced to the article it implements; see `docs/static-review.md`
  and the generated `docs/rules.md`.
- `test-review` finds tests that cannot fail (article 3): no assertion, always-true assertions,
  empty bodies, swallowed failures; `k8s-review` also checks Argo Rollouts and Flagger canaries and
  blue-green rollouts (articles 53, 54); `ci-review` flags `helm upgrade` without `--atomic`
  and `--timeout` (article 70).
- 26 more offline failure signatures (34 in total) for `debug` and `triage` (image pull, scheduling, eviction,
  SIGKILL, RBAC, missing CRD, TLS, DNS, disk, Git and registry authentication, runner
  failures, Helm release failures and more). Symptoms no longer conflict with the category.
- `RADEA_INTERNAL_DOMAINS` to alias organisation-specific hostnames.
- PyYAML as a runtime dependency (`safe_load` semantics only); lock files regenerated.
- mypy runs in CI; `docs/feature-matrix.uk.md` now covers all 80 articles.

### Security
- Sanitizer: GitLab, Slack, Stripe, npm, PyPI, Google, SendGrid and Docker tokens, bare JWTs,
  `.netrc` passwords, Azure/SAS keys, kubeconfig key data, zero-width and full-width
  obfuscation, sensitive key names in JSON.
- Sanitizer: fixed quadratic regex backtracking. One hostile 64 KiB line previously took
  minutes (8 KiB took about 3 s); it now takes about a second at worst.
- Model output: unknown fields inside `hypotheses`, `findings`, `patterns` and `timeline`
  entries are now discarded, not only at the top level.
- The `internal_host` rule no longer mangles public hosts such as `corp-example.net`.

### Fixed
- Generated service images keep application code readable by the non-root user under a strict
  host umask.
- mypy errors in provider diagnostics, packaged data access and PR comment validation.
- Own workflows now declare job timeouts and pass `ci-review`.

## 0.2.0rc1

Initial public release candidate of RADEA.
