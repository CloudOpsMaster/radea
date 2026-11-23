# Deterministic reviews

RADEA's analysis commands (`debug`, `iac-review`, `triage`) read logs and may use a model. The
commands below never do: they read files, apply fixed rules and print the same result every time.
No model, no network, no cluster or cloud credentials, no GPU. Every finding comes from a rule
in the [rule reference](rules.md) with its severity, the reason, the fix and the article it
implements.

| Command | Reads | Looks for |
| --- | --- | --- |
| `k8s-review PATH...` | Rendered manifests, Helm chart sources | Probes, image pinning, requests/limits, security context, rollout strategy, replicas and PDBs, selectors, HPA/VPA conflicts, RBAC, secrets, Service selectors, chart hygiene |
| `dockerfile-review PATH...` | `Dockerfile`, `Dockerfile.*`, `*.dockerfile` | Mutable tags, root user, baked-in secrets, remote scripts, cache and layer hygiene, build tools in the final image |
| `ci-review PATH...` | GitHub Actions workflows, GitLab CI files | Unpinned actions/includes, privileged triggers, script injection, curl-to-shell, printed secrets, ignored security failures, floating image tags |
| `tf-review PATH...` | Terraform `.tf` files | World-open ingress, literal secrets, disabled encryption, public exposure, unpinned providers and modules, missing destroy guards |
| `vuln-triage REPORT...` | Grype or Trivy JSON | Groups by package, ranks by severity and fix availability, counts what is hidden |
| `flaky JUNIT...` | Several JUnit XML runs | Tests that both pass and fail (flaky) versus tests that always fail (broken) |
| `rightsize USAGE...` | JSON of observed p95/p99 usage | Requests and limits that disagree with usage, with recommended values |
| `changelog` | A git range | Technical changelog, release-note draft and a commit-hygiene report |
| `policy-check --plan` | `terraform show -json` | Destructive plan actions (blocking gate, existing command) |
| `rules` | Nothing | Lists every rule |

## Exit codes and gating

`k8s-review`, `dockerfile-review`, `ci-review`, `tf-review`, `vuln-triage`, `flaky` and
`rightsize` share one contract, the same as `policy-check`:

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
