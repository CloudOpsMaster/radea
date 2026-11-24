# RADEA — Reliable AI-Driven Engineering Automation

Offline by default. Review every draft.

RADEA is a Python CLI for CI failure analysis, Terraform review and incident log
summaries. It drafts recommendations; it does not execute suggested commands or
apply infrastructure changes. Rules run locally by default, without a GPU, model
server, API key or inference network request. Cloud models are an explicit opt-in.

Beyond the three analysis commands, RADEA ships deterministic reviews that never use a model:
Kubernetes and Helm, Dockerfiles, CI configuration, Terraform, vulnerability reports, flaky
tests, right-sizing and changelog drafts. See [deterministic reviews](docs/static-review.md).

Run the [hands-on demo](docs/demo.md) locally or open **Actions → RADEA Demo**
to explore failure triage, release gates and incident review with downloadable evidence.

## Install

Requires Python 3.10+. From a source checkout:

```sh
git clone https://github.com/CloudOpsMaster/radea.git
cd radea
python -m pip install .
radea --help
radea doctor --output json
```

## Quick start without credentials

```sh
radea debug --log examples/logs/failed-build.log
radea iac-review --file examples/terraform/main.tf
radea triage --logs examples/logs/incident.log
```

These commands produce evidence-linked drafts using local rules. Unknown signals
remain unknown. Add `--dry-run` to preview sanitized evidence instead of analyzing it.
See [offline engines and measured comparison](docs/offline.md).

## Deterministic reviews (no model, no network)

```sh
radea k8s-review manifests/                 # or: helm template ./chart | radea k8s-review -
radea dockerfile-review .
radea ci-review .gitlab-ci.yml .github/workflows
radea tf-review infra/
radea vuln-triage scan.json                 # Grype or Trivy JSON
radea flaky build/results/run-*.xml         # several JUnit runs of the same code
radea test-review tests/                    # tests that cannot fail: no assertion, assert True
radea rightsize usage.json                  # observed p95/p99 versus requests and limits
radea changelog --from v1.4.0               # a draft; a human approves it
radea rules                                 # every rule, severity and source article
```

Each review exits 0 when clean, 2 when a finding reaches `--fail-on` (default `high`) and 1 on
invalid input, so any of them can gate a pipeline. Findings name a rule, a file and line, the
reason and the fix; secret values are never printed. Rules are listed in the
[rule reference](docs/rules.md). They are static: no cluster, registry or cloud API is
contacted, nothing is executed, and no findings does not prove safety.

Use `radea threat-review model.json` to draft defensive STRIDE checks from an abstract
data-flow model and `radea threat-disposition draft.json decisions.json` to record decisions.

### Code review and platform starters

- `radea code-review PATH` checks Python source and reports line-specific mechanical defects.
- `radea docs-answer "How do Helm rollbacks work?" docs` returns cited local documentation.
  `radea docs-backlog gaps.jsonl` ranks unanswered request categories.
- `radea migration-route plan.json --path /healthz --cohort sample` previews a staged route.
  `radea migration-serve plan.json --legacy-port 8001 --candidate-port 8002` serves it locally.
- `radea cutover-plan plan.json --fail-at switch` validates a runbook and rehearses rollback order.
- `radea helm-matrix old-chart new-chart --values prod=prod.yaml` compares chart renders.
- `radea image-verify --help` verifies a detached image signature with a trusted public key.
- `radea shell-review new.sh --baseline old.sh` compares ShellCheck diagnostics.
- `radea shell-graph ci/build.sh --root .` traces local shell script references using shfmt.
- `radea service-scaffold --help` creates a Python service with tests, a hardened Dockerfile,
  and a minimal GitHub Actions workflow for review.

### Kubernetes and incident operations

- `radea k8s-capture POD --help` reads Pod health and related events, with opt-in redacted logs.
- `radea k8s-debug-plan pod.json --help` prepares a restricted ephemeral probe patch.
- `radea k8s-smoke CASES.json --help` gates HTTP smoke checks on Deployment readiness.
- `radea crd-validate CRD.yaml --help` checks a CRD with strict server-side dry-run.
- `radea preview-env --help` manages per-PR Kubernetes previews in an explicit context.
  `radea preview-pr --help` connects the lifecycle to trusted GitHub PR events.
  `radea preview-sweep --help` plans or applies TTL cleanup.
- `radea k8s-workload-plan --per-pod-storage` recommends a workload controller.
- `radea flag-evaluate flags.json checkout --cohort demo --group beta` evaluates a targeted rollout.
- `radea flag-experiment observations.json --control control` compares observed variant outcomes.
- `radea postmortem-review draft.json review.json` records human decisions bound to a triage draft.
- `radea prompt-prepare library.json context.json --template incident --version 1` prepares a team prompt.
- `radea test-scaffold cases.json --module app --function parse` drafts executable pytest cases.

### Pipeline migration and Kubernetes snapshots

- `radea helm-kustomize-diff ./chart ./overlays/staging --values staging.yaml --fail-on-change` compares the rendered Helm and Kustomize resources.
- `radea shell-parity old.sh new.sh cases.json --execute` compares behavior for shared argument and stdin fixtures using trusted local scripts.
- `radea learn-readiness --help` opens an offline Kubernetes exercise with starter YAML, a hint and automatic feedback.
- `radea helm-review ./chart --values staging.yaml` runs strict Helm lint, values validation, rendering and static Kubernetes review.
- `radea ci-graph pipeline.yml` reports local job order and dependencies. Pass `--gitlab-root .` to expand literal local GitLab includes.
- `radea ci-observe logs/ --threshold 3 --watch 30` watches aggregated CI failure counts.
- `radea ci-translate gitlab.yml` drafts a manual GitHub Actions workflow for simple GitLab
  shell jobs. `radea ci-diff gitlab.yml github.yml` compares the two job graphs.
- `radea k8s-health pods.json` reports symptoms from a captured Kubernetes Pod snapshot.
  `radea k8s-drift desired.yaml observed.json` compares declared fields with observed resources.
- `radea tf-drift plan.json` reports refresh drift recorded in a Terraform plan.
- `radea metric-anomalies series.json` measures deviations from recent metric or cost readings.
- `radea telemetry-capture capture` receives local OTLP/HTTP JSON correlation data.
- `radea telemetry-review traces.jsonl --logs logs.jsonl --metrics metrics.jsonl` correlates
  captured OpenTelemetry signals locally.
- `radea pilot-report cases.json` measures net time saved across paired baseline and assisted
  runs, including verification and rework.

- `radea gitops-sync --help` reconciles a committed bundle, with optional remote fetch and ApplySet pruning.
- `radea dora-report events.json` calculates five delivery metrics from production deployment events.
- `radea sbom-review bom.json scan.json` matches scanner findings to CycloneDX dependencies.
- `radea rbac-access snapshot.yaml --help` explains resource access from RBAC bindings.
- `radea ci-shadow baseline.xml candidate.xml` compares observed test outcomes across pipelines.
- `radea ci-timing timings.json` compares feedback time, parallelism and cache observations.
- `radea cost-report export.csv --by ServiceName --tag team` allocates billed costs.
- `radea dependency-review approved.json proposed.json --fail-on-unapproved` checks dependencies.
- `radea secret-migration-plan inventory.json --require-ready` tracks secret migration checks.
- `radea repo-contract-check api.json client.json --fail-on-change` checks shared contract versions.
- `radea tf-plan-diff old.json new.json --fail-on-change` gates resource plan changes.
- `radea rebuild-check original.json rebuilt.json --fail-on-change` compares server inventories.
- `radea iam-simulation-review export.json cases.json --fail-on-mismatch` checks IAM expectations.
- `radea canary-gate measurements.json --max-p95-ms 200` evaluates promotion thresholds.
- `radea cutover-rehearse --help` shows how to rehearse a staged HTTPRoute cutover and verify restoration.
- `radea migration-parity --legacy http://127.0.0.1:8081 --candidate http://127.0.0.1:8082 --path /catalog` compares read-only responses before routing traffic.
- `radea gateway-route --namespace apps --gateway edge --route migration --stable legacy --candidate replacement --path-prefix /catalog` renders a Gateway API HTTPRoute for a migration slice.
- `radea gateway-rollout --kubeconfig cluster.yaml --context staging --namespace apps --route migration --stable legacy --candidate replacement --weight 10 --apply` starts a 90/10 split. Pass `--prometheus` and `--policy` in place of `--weight` to evaluate live telemetry. See the [Gateway rollout guide](docs/gateway-rollout.md).

- `radea mutation-test module.py test_module.py` runs trusted Python unit tests against mutations.
- `radea mutation-suite . --package src/app --tests tests` checks multiple package modules.

### Local Kubernetes release lab

Compare generated manifests with `radea manifest-diff before.yaml after.yaml --output json`.
Run `tools/k8s_lab.sh` for Helm linting, schema validation, manifest review and a rendered diff.
Run `tools/k8s_lab.sh --gateway` to exercise Envoy Gateway and Prometheus in an isolated cluster.
Run `tools/k8s_lab.sh --source-to-pod` to test, build, deploy and probe a generated Python service.
Run `tools/k8s_lab.sh --operator` to build and test the namespaced Message controller in Kubernetes.
Run `tools/k8s_lab.sh --telemetry` to test Collector and RADEA capture containers in one Pod.
With Minikube and a working local driver, `tools/k8s_lab.sh --minikube` also installs, upgrades,
tests and rolls back the example release in a disposable profile. It also exercises
canary and blue-green traffic switching, a namespaced custom-resource controller, and
a Git-backed feature flag updated without a Deployment rollout. See
[the static review guide](docs/static-review.md#rendered-manifest-diff-and-kubernetes-lab).

## Models and runners without GPUs

`RADEA_MODEL=offline` is the default. It uses bounded parsers and rules, with no
model download or training on the runner. Experimental `offline-linear` and
`offline-neural` add a category hint to `debug`; they never override rules or gates.
Their bundled weights are small JSON files and require no ML framework.

Choose a cloud API or Kiro explicitly when you want remote model analysis. Network
access, provider authentication and quota are then required. Unknown providers fail;
there is no automatic fallback or silent switch to cloud inference.

| Selection (`RADEA_MODEL`) | Authentication | Inference |
| --- | --- | --- |
| `offline` (default) | None | Local rules |
| `offline-linear`, `offline-neural` | None | Rules + experimental category hint |
| `openai/<model-id>` | `OPENAI_API_KEY`; install `.[openai]` | Cloud |
| `anthropic/<model-id>` | `ANTHROPIC_API_KEY`; install `.[anthropic]` | Cloud |
| `google/<model-id>` | `GOOGLE_API_KEY`; install `.[google]` | Cloud |
| `kiro` or `kiro/<model-id>` | Installed, authenticated `kiro-cli` | Kiro service |
| `ollama/<model-id>` | Running Ollama server with model installed | Configured server |

Model IDs must be available in your provider account. An unprefixed model name
selects OpenAI; use an explicit provider prefix for clarity. Base installation
excludes cloud SDKs. Install `.[all]` to include every supported provider SDK.

```sh
export RADEA_MODEL=kiro
radea debug --log examples/logs/failed-build.log

# Optional: choose a model supported by your installed Kiro CLI/account
# export RADEA_MODEL=kiro/<model-id>
```

Kiro runs with `chat --no-interactive --agent radea-analysis` in a temporary
working directory. RADEA supplies an agent with no tools or resources and passes
the sanitized input through stdin. It does not enable `--trust-all-tools`.
Install and authenticate Kiro separately using the
[official instructions](https://kiro.dev/docs/cli/authentication/). CI credentials
must support headless operation; an interactive laptop login is not a CI setup.
Set `RADEA_KIRO_TIMEOUT` to change the 120-second process timeout.
This adapter is covered by mocked process tests; live Kiro compatibility must be
verified against your installed CLI version before relying on it in CI.

For Ollama:

```sh
python -m pip install ".[ollama]"
export RADEA_MODEL=ollama/llama3.2
radea debug --log examples/logs/failed-build.log --local
```

`--local` or `RADEA_LOCAL=true` forces Ollama. If the selected model is not an
Ollama model, it uses `llama3.2`. `RADEA_OLLAMA_URL` defaults to
`http://localhost:11434`. Local CPU inference is possible but needs sufficient
RAM and can be slow. A remote Ollama URL requires HTTPS and explicit
`RADEA_ALLOW_REMOTE_OLLAMA=true`. `--local` rejects non-loopback endpoints. Use cloud
inference only when explicitly selected; the default rules work on constrained
runners without inference. `--local` is the legacy Ollama switch, not the offline engine.

## Commands

```sh
radea debug --log ci.log --output json
radea iac-review --file main.tf --plan plan.json --context conventions.md
radea triage --logs ./logs/ --metrics metrics.json --baseline 7d
radea post-comment result.json
```

Analysis commands support `--local`, `--dry-run`, and `--output text|json`.
Provider failures appear in output and produce exit code 1. Dry-run previews
support both text and JSON output. `post-comment` writes to GitHub/GitLab when configured; otherwise
it prints Markdown. See [CI integration](docs/ci-integration.md).

Configuration uses environment variables; there is no `radea config` command.
`RADEA_MAX_LOG_CHARS` defaults to a 32,000-character source-context budget (JSON
structure adds overhead; total payload is capped at four times that budget).
`RADEA_MAX_INPUT_BYTES` defaults to 8 MiB per file, with at most 32 source files
and 64 KiB per line. Logs are read with bounded memory, preserving head and tail;
omissions and clipped lines are explicit. Terraform plans are fully parsed within
the byte limit; oversized or invalid plans fail. Plan facts have their own evidence
budget and cannot be pushed out by a long Terraform source file.

A private metadata-only audit log is written to `~/.radea/audit.jsonl` with mode
0600. Set `RADEA_AUDIT_DIR` to a private writable directory or `RADEA_AUDIT=false`
to explicitly disable it. It records command, provider/model, prompt/input hashes,
status and duration, never raw prompts, responses, credentials or exception text.
An enabled audit write failure prevents the request from proceeding.

Incident metrics use this explicit schema:

```json
{"baseline":{"window":"7d","values":{"latency_p95":100}},"current":{"latency_p95":125}}
```

Matching keys and finite numbers are required. RADEA computes deltas/percentages
locally, with `null` percentage for zero baselines. It does not fetch history or
infer statistical significance. Humans own the final incident cause and action items.

## Data handling

Sanitization detects common AWS credentials, GitHub and GitLab tokens, Slack, Stripe, npm,
PyPI, Google and SendGrid tokens, JWTs, authorization headers, private keys, URL passwords,
`.netrc` passwords, cloud connection-string keys, kubeconfig key data and secret assignments.
Invisible and full-width characters are normalised first so they cannot hide a key name. Set
`RADEA_INTERNAL_DOMAINS=corp.example,lab.example` to also alias your own hostnames. It is best effort:
review inputs before sending sensitive material. Common internal hostnames, private
IPv4 addresses and emails use stable request-local placeholders (up to 1,024 aliases,
then a generic placeholder). Detection of every sensitive value is not guaranteed.
`debug --no-sanitize` is rejected; remote and local input paths require redaction.
Terraform context and incident metrics are also sanitized.

## Acceptance checks

`radea doctor --output json` checks client/configuration presence without inference.
`radea smoke --live --output json` explicitly permits one synthetic provider request;
provider charges may apply. Neither a configured client nor a successful synthetic
request certifies diagnostic accuracy. See [acceptance evidence](docs/acceptance.md).

## Python API

```python
from radea.api import AnalysisRequest, analyze

result = analyze(AnalysisRequest(command="debug", paths=("ci.log",)))
```

The API returns data without printing. Reuse `AnalysisService` for explicit configuration
and an injectable model transport; every adapter uses the same guardrails.
See [architecture and integration examples](docs/architecture.md) and the
[complete 80-article feature matrix](docs/feature-matrix.md).

## Verification and policy

All analysis JSON uses `schema_version: "1.0"`, `draft: true`, `verified: false`,
provenance hashes and an evidence map. Each model claim needs existing evidence IDs;
quoted source lines must match. `evidence_verified` means references were checked,
**not** that the diagnosis is correct. Arbitrary JSON objects and malformed results
fail validation. Postmortem causes are explicitly unverified hypotheses; human
conclusions/action items remain separate.

Terraform delete/replace is derived locally even if the model omits it or fails.
Literal IAM Action/Resource wildcard findings are also independent of the model;
these rules are not a full IAM/RBAC analyzer. Without a plan, destruction is marked
not assessed. Incomplete plans cannot pass the deterministic policy gate:

```sh
radea policy-check --plan plan.json
```

This command never calls a model. Exit 0 allows, 2 denies, 1 indicates invalid input.
`--allow-destruction` is an explicit human exception, not an AI decision.
See [trust boundaries](docs/threat-model.md) and [evaluation](docs/evaluation.md).

## Development and release

```sh
python -m pip install --require-hashes -r requirements-ci.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest
ruff check src tests
```

The shared CI runs tests on Python 3.10–3.12, lint, dependency vulnerability
scanning, static security analysis, distribution validation and an installed-wheel
smoke test. It runs on pull requests and pushes to main, and is reused before tag
releases. Security unit tests run with the ordinary Python suite; dependency and
static scans are separate steps in the same CI workflow.

Branch rules must require these jobs; owner-only write protection is a separate control. Workflow
files alone do not block merging. The manual demo uses dry run without API keys.
Tag releases promote the tested wheel/sdist, checksums, runtime dependency SBOM
and provenance to a GitHub Release; they do not publish
to PyPI. Automated tests mock model calls and consume no inference credits.

See [contributing](CONTRIBUTING.md) and [security policy](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
