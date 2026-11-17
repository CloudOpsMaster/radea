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
