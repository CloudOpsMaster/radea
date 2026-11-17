# Acceptance evidence

Acceptance distinguishes real external transport, controlled inference fixtures,
resource measurements and actual live provider inference. They are not interchangeable.

## Real GitHub transport — passed

A temporary draft PR used a controlled failing test on a same-repository branch.
The real [Actions run](https://github.com/CloudOpsMaster/radea/actions/runs/44131202345)
produced three failed test jobs. RADEA downloaded their text logs over the GitHub API,
resolved the open PR at the exact head SHA, validated the evidence and published a
[clearly marked fixture comment](https://github.com/CloudOpsMaster/radea/pull/2#issuecomment-6954874258).
The temporary PR was closed after the test and its failure never entered main.

Inference in this scenario was **deterministic fixture data**, with
`provenance.transport=injected`. No external LLM was called. This proves real GitHub
read/write wiring, not model quality, live SDK authentication, or unattended workflow
installation in another organization's environment.

This run exposed and reproduced an Actions edge case: `pull_requests` can be empty
for a PR workflow run. The adapter now resolves only one open same-repository PR
matching both branch and exact head SHA. Ambiguous and stale matches are rejected.

Reproduce explicitly using tools/verify_github_transport.py with a controlled failed
run, a known open fixture PR and a scoped GITHUB_TOKEN. `--post-fixture-comment`
requires an explicit opt-in. Never point the fixture tool at a production incident.

## Resource acceptance

`tools/benchmark_runner.py` now measures a **complete offline debug analysis**, not
only a dry-run preview. It generates a 6 MiB synthetic log, preserves the final
failure and reports omitted lines. Run `--model offline-linear` or
`--model offline-neural` for the experimental hints in separate processes.

Local macOS measurements were approximately 28 MiB peak RSS and 2.7 seconds per
complete run; CPU/memory limits were not enforced locally. CI enforces 256 MiB
address space, one available CPU, a 30-second CPU budget and peak RSS below 128 MiB
for each engine. Read its `runner-benchmark.json`, `linear-benchmark.json` and
`neural-benchmark.json` artifacts for the actual constrained Linux measurements.
Historical dry-run measurements from the earlier prerelease do not measure the new engine.

The packaged wheel is also tested without any OpenAI SDK installed, running all
three analysis commands without dry-run. Neither benchmark training nor downloads
of model weights take place in CI.

## Live providers — explicit opt-in

```sh
radea doctor --output json
radea smoke --live --output json
```

Doctor never contacts a provider or prints a key. `configured=true` means the client
and required configuration were found; it does not claim authentication succeeded.
The smoke command makes at most one synthetic guarded analysis request when readiness
checks permit it. It validates the response contract, not general diagnostic accuracy.
Kiro-managed authentication cannot be inferred from the presence of an env key.
Failures retain allowlisted provider error codes and HTTP status without exception
bodies. Billing/quota errors are marked non-retryable; temporary rate limits are
distinguished from them. Resolve the reported account limit before starting a batch
of live tests; repeated quota failures do not validate model behavior.

`Live provider smoke` is a manual workflow. Configure the appropriate GitHub Secret
and pass an explicit model. API SDK dependencies are hash-locked separately in
requirements-providers.lock. The hosted workflow does not install or authenticate Kiro;
use an authenticated Kiro CLI environment for that backend.

At preparation time no provider API credentials or kiro-cli were available locally
or configured in repository secrets. These are external prerequisites, not passing tests.

## Dependency graph coverage

GitHub's full lock graph exposed 17 filelock advisories in the Python 3.10 tooling
branch that a Python 3.12/3.14-only pip-audit invocation skipped by environment markers.
CI-only pip-audit now runs on Python >=3.11 and filelock is constrained to >=4.2.1;
the vulnerable 4.1.0 resolution is removed. Runtime and test support for Python 3.10
remain in place. Optional provider SDKs have a separate hash-locked audit as well.
PRs also run GitHub dependency review across the complete lock graph, rather than
relying only on interpreter-specific installed-package auditing. No advisory is
dismissed to hide an unsupported interpreter resolution.

## Candidate release

Release candidates use PEP 440 versions such as 0.1.1rc1 and matching v-prefixed tags.
The workflow verifies metadata/tag agreement and publishes candidates as pre-releases,
without marking them latest. The released wheel is the same artifact checked by CI;
checksums, runtime dependency SBOM, runner measurement and provenance accompany it.
A configured workflow alone is not evidence of a successful release: retain the run
URL and verify downloaded assets and attestation after publication.
