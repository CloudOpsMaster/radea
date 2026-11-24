# RADEA trust boundaries

RADEA is an advisory CLI. Model fluency is never authorization or proof.

| Boundary / threat | Control | Remaining responsibility |
| --- | --- | --- |
| Logs/config contain credentials or PII | Redaction before payload construction; private-key streaming state; output redaction; dry run | Pattern scrubbing is best effort. Do not submit regulated data or secrets expecting perfect DLP. |
| Logs contain prompt injection | Input marked untrusted, model gets no execution tools, strict response schema and evidence IDs | A model can still draw a wrong conclusion from genuine evidence; human verification is required. |
| Model omits a destructive operation | Full bounded Terraform plan parsed locally, independent delete/replace list and policy-check | Plan authenticity and freshness belong to the trusted planning job. |
| Huge inputs / token cost | Per-file byte, line, file-count, context and response limits; tail preservation; explicit omission metadata | Inputs over limits fail, not silently succeed. Provider quotas still apply. |
| Unknown provider / remote endpoint | Fail-closed provider parsing; remote Ollama opt-in + HTTPS; local flag enforces loopback | DNS/proxy routing and network egress policy belong to the runner administrator. |
| Compromised external CLI | Tool-free Kiro profile, temporary cwd, minimal environment, process timeout | This is not an OS sandbox. Pin and authenticate the real CLI; isolate HOME and restrict egress at runner/container level. |
| Privileged workflow consumes fork data | GitHub adapter rejects fork runs; checks out only reviewed RADEA SHA; no Terraform execution | Keep the upstream planning workflow trusted; never expose deployment credentials to unreviewed PR code/providers. |
| Credential forwarding during redirects | Download redirects use HTTPS and omit Authorization; comment requests prohibit redirects | Admin controls the configured GitLab API origin. |
| AI output spoofs authority | draft=true, verified=false, provenance hashes; citations validated before posting | Citations prove source membership, not causal correctness. Anyone editing a result file can change its contents. |
| Audit leaks secrets | Private 0600 metadata-only records; no prompts, responses, paths or exception bodies | Protect/rotate audit storage. Hashes are identifiers, not encryption or cryptographic attestations of model reasoning. |
| Supply-chain substitution | Committed universal lock and hashed CI/runtime exports, actions by SHA, SBOM, tested-artifact promotion | Review lock updates and provider releases. Public model aliases may change server-side. |

Deployment, permission changes and remediation remain human-owned. `policy-check`
is deterministic and separate from LLM review; it rejects incomplete plans and
requires an explicit exception for delete/replace. Literal IAM wildcard rules
are advisory and are not a complete IAM/RBAC authorization analyzer. Use your
organization's policy engine and cloud access analyzer for broader enforcement.

Offline is the default analysis strategy. Available API credentials alone do not
activate a provider. Optional tiny classifiers load only bundled, bounded JSON
numeric weights with fixed shapes, never pickle or executable model files. Their
score margins are not probabilities, and hints cannot override policy or rule
findings. Hashes identify artifacts; they do not certify predictive accuracy.

## Deterministic review inputs

`k8s-review`, `dockerfile-review`, `ci-review`, `tf-review`, `test-review`, `vuln-triage`, `flaky`,
`rightsize`
and `changelog` read files that may come from an untrusted pull request. They never execute
anything, but their parsers are still an attack surface, so:

* Files are size-limited (`RADEA_MAX_INPUT_BYTES`), capped at 500 per run, and symlinks found
  while walking a directory are not followed.
* YAML uses a safe loader; custom tags become plain data and are never instantiated; aliases
  are counted once so an alias bomb cannot exhaust memory; nesting depth is bounded.
* XML with a DOCTYPE or entity declaration is rejected before parsing.
* The Terraform reader is a small tolerant scanner with no recursion on untrusted nesting
  beyond block depth and is fuzzed with malformed input in the tests.
* `changelog` calls `git` with a fixed argument list and no shell; refs that start with `-`,
  contain `..` or unusual characters are rejected, and the child environment is minimal.
* Regular expressions that run on every line are bounded and guarded by required substrings;
  a 64 KiB hostile line must sanitize in about a second (regression-tested).
* Python test files are parsed with `ast` only: they are never imported or executed.
* Output passes through the sanitizer; environment values, Secret data and Terraform
  attributes are reported by name only.


## Commands with execution or writes

`gitops-sync` applies committed ConfigMaps and ClusterIP Services to a named namespace.
Use a trusted repository and explicit kubeconfig and context. A namespace-scoped RBAC
identity can limit the apply permissions. Server-side ownership conflicts require an
explicit option to override. A failed multi-resource apply can leave earlier resources
updated, so inspect live state before retrying.

`mutation-test` executes the selected Python module and pytest test file with the local
process permissions. Temporary working directories isolate mutation files. They provide
file hygiene rather than a process sandbox. Run it with code you trust.
