# CI integration

The supported GitHub adapter is tested offline end to end using recorded API shapes
and a mocked model. Live model inference and every CI vendor are not certified.
The templates in `ci/` are opt-in examples, not installed workflows in RADEA itself.

## Interactive walkthrough

Run the [RADEA Demo](demo.md) to explore fixture-based analysis, policy gates,
release decisions and downloadable reports before wiring live CI inputs.

## Build, deploy and evaluate a preview

In **Actions → RADEA Delivery Demo → Run workflow**, try **healthy**,
**insufficient-samples**, or **unhealthy**. The
[workflow](../.github/workflows/delivery-demo.yml) checks out the sample site,
packages it, deploys the archive to an HTTP server on the runner and records
the health responses before invoking RADEA.

| Candidate | Measurements | RADEA decision |
| --- | --- | --- |
| Healthy | Five successful health requests | Promote, exit 0 |
| Insufficient samples | One successful health request | Hold, exit 3 |
| Unhealthy | Five health requests to a missing endpoint | Rollback, exit 2 |

Only a promote decision allows the downstream confirmation step. The demo
publishes the decision and observed measurements to the run summary and
uploads the measurement JSON, decision report, and preview server log.
The runner's preview stops at the end of the measurement step.

To adapt this to another repository, add the workflow under
`.github/workflows/`. Check out RADEA as a second repository at a reviewed
commit SHA and install it with the lockfile from that checkout. Replace the
static build and loopback preview with your build and staging deployment.
Pass candidate-specific request measurements to `radea canary-gate`, then
use your deployment system to promote or restore traffic. Give those
operations their own scoped credentials.

## GitHub failure triage

1. Copy `ci/github-actions/radea-debug.yml` into your repository's `.github/workflows/`.
2. Set repository variable `RADEA_REF` to a reviewed **40-character RADEA commit SHA**.
3. No model credentials are needed for the default offline rules. For cloud analysis,
   explicitly set `RADEA_MODEL` and the matching provider secret/SDK.
4. Set `workflows: ["CI"]` to your upstream CI workflow name.

The privileged job checks out that exact RADEA revision, installs hashed dependencies,
fetches **text logs for failed jobs**, sanitizes them, validates evidence references,
and posts an AI DRAFT comment for a single same-repository PR. Fork runs and ambiguous
PR targets are skipped. At most four failed jobs from the first 100 jobs are collected;
omissions are explicit. Oversized log responses fail instead of being treated as complete.
No PR code is executed by this adapter. Read-only GitHub API calls use actions: read;
comments use pull-requests: write. Redirected downloads never forward the token.

## GitHub Terraform review

Use a **separate trusted** workflow named `Terraform Plan` to produce `terraform show -json`
output. Upload exactly one artifact named `terraform-plan`, containing only `plan.json`.
Do not run Terraform providers from untrusted PR code with deployment credentials.
Copy `ci/github-actions/radea-iac-review.yml` into `.github/workflows/`, and configure the
same RADEA_REF, model and secret. The adapter validates the artifact path and size,
parses the plan as data, detects delete/replace locally and posts a validated draft.
It never runs Terraform, applies changes or checks out PR code.

For a deterministic gate in your trusted plan job:

```sh
radea policy-check --plan plan.json
# Exit 0: policy allowed; 2: denied; 1: input/configuration error.
# An authorized human can explicitly choose --allow-destruction.
```

Advisory `iac-review` does not block on findings; operational/validation errors return 1.
Never use a model's empty findings as authorization. Require your deterministic checks
in branch rules. Owner-only main is a separate write-control rule and remains in effect.

## Local result and comment flow

```sh
radea debug --log ci.log --output json > result.json
radea post-comment result.json
```

Only schema-versioned, evidence-validated draft results can be posted. GitHub requires
GITHUB_ACTIONS, GITHUB_TOKEN, GITHUB_REPOSITORY and a PR_NUMBER or event payload.
GitLab requires GITLAB_CI, GITLAB_TOKEN (a scoped project/user API token), CI_API_V4_URL,
CI_PROJECT_ID and CI_MERGE_REQUEST_IID. CI_JOB_TOKEN is not used as a personal API token.
Without a recognized CI environment, the command prints the draft comment.

Comments are explicitly generated drafts; no source change, review approval or merge
is performed. Use a separate approval step before posting if your communication policy
requires a human to review every generated message.

## Other vendors

GitLab, Jenkins, CircleCI, Azure DevOps, Bitbucket and Drone templates are **experimental**.
They require vendor-specific log collection and credential validation before use. They
are not covered by live end-to-end tests. Set a reviewed RADEA_REF and validate the
pipeline's behavior with the vendor's own tooling. Do not treat them as turnkey support.

## Reproducible delivery of RADEA

`requirements-ci.lock` pins CI/build/security tooling with hashes across supported Python
versions; `requirements-runtime.lock` pins base runtime dependencies. `uv.lock` also resolves
optional providers. Update intentionally with uv 0.13.9:

```sh
uv lock
uv export --frozen --extra dev --group tooling --no-emit-project -o requirements-ci.lock
uv export --frozen --no-emit-project --no-dev -o requirements-runtime.lock
```

CI builds once, checks the wheel and sdist, smoke-tests the installed wheel, produces a
CycloneDX runtime-dependency inventory and SHA256SUMS, and uploads the distribution artifact.
A version tag reuses the shared checks. Candidate versions are marked pre-release
and never become latest. A constrained Linux runner measurement is retained with the artifacts. Release downloads that **same tested artifact**,
verifies checksums and tag/version agreement, creates a GitHub provenance attestation,
and attaches it to the Release. No second build and no automatic PyPI publication occur.
