# RADEA audit and implementation status

Deterministic reviews cover Kubernetes, Helm, Dockerfiles, CI and Terraform.
Static rules cover Argo Rollouts and Flagger for blue-green and canary delivery.
The Helm lab covers rendering, schema validation, manifest comparison, and an
install, upgrade, Service test and rollback sequence in Minikube. The
[article matrix](feature-matrix.md) maps all 80 articles to practical scenarios
and records their limits. [Manual review exercises](evaluation.md#practice-manual-review-and-handoff)
show how engineers verify drafts and hand off decisions.

The basic lab uses local Helm and RADEA. Pod-level scenarios require a usable
Minikube driver. QEMU-backed Minikube runs verified Service HTTP, Helm rollback,
manual canary and blue-green switching, GitOps rollback, admission by verified
digest, the Message operator, isolated PR previews, a restricted ephemeral
probe, and correlation of three OTLP signals through a Collector. The Message
operator checks included schema rejection, reconciliation, status and cleanup
of the owned resource.

| Audit gap | Implemented control | Verification |
| --- | --- | --- |
| F1 — Secrets and PII | Redacts structured and short assignments, URLs, signed URLs, PEM, internal hosts, emails and private IPv4. Redacts output again and rejects raw bypass. | Positive and negative fixtures and a redacted PR flow. |
| F2 — Model-dependent risk findings | Bounded plan parsing, local delete and replace detection, literal IAM rules, and deterministic policy decisions. | Destructive actions remain visible with empty responses and model errors. Allow and deny fixtures exercise the policy. |
| F3 — Unsupported claims | Per-command response contracts, evidence IDs, exact quotes, unknown-field rejection and controlled errors. | Fabricated evidence, incorrect quotes and types, and spoofed metadata. |
| F4 — Lost context | Bounded streaming, head and tail sampling, omission metadata and a separate plan budget. | Tail failures, large Terraform files, oversized lines and PEM in the tail. |
| F5 — Missing audit and provenance | Draft and verification fields, private metadata-only audit, human conclusions and baseline deltas. | Audit privacy, permissions and write failures. Matched metrics and zero baselines. |
| F6 — Integration boundaries | GitHub job text logs and bounded plan artifacts are processed without executing PR code. Other vendor adapters are experimental. | API payload through the model boundary to validated comments, plus fork, redirect and artifact rejection cases. |
| F7 — Supply chain | uv lock, hashed exports, pinned actions, SBOM, checksums, promotion of tested artifacts and provenance. | Locked installs, Python matrix, wheel smoke tests and workflow contracts. |
| F8 — Provider trust | Unknown providers are rejected. Remote Ollama is opt-in with HTTPS. Local Ollama stays on loopback. Kiro gets a reduced environment. | Routing rejection cases and credential exclusion in a test child executable. |

Required reviews and checks depend on GitHub branch rules. The documented
configuration restricts writes to main and requires a PR and all five CI
checks without bypass. Verify those settings when migrating the repository.

Redaction is best effort. Valid citations make evidence traceable, and human
review establishes what the evidence supports. Literal IAM checks cover
policy patterns. Validate effective permissions with the target authorization
system. Kiro tool limits and working-directory restrictions require a
separate OS isolation boundary when one is needed. Real provider quality and
time savings require live smoke tests and a human-scored pilot with
representative cases. [Acceptance evidence](acceptance.md) ·
[Evaluation](evaluation.md) · [Threat model](threat-model.md)
