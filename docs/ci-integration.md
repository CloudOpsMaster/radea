# CI Integration Guide

RADEA attaches to your existing pipeline at two points and never modifies it:

```
your pipeline:  checkout → build → test → deploy
                               │                  │
                         (on failure)       (on .tf change)
                          radea debug       radea iac-review
                               │                  │
                         PR comment          PR comment
                         with ranked         with findings
                         hypotheses          and STOP warning
```

RADEA never blocks a merge. Every output is marked AI DRAFT.
The engineer reads it and decides what to do.

---

## Supported platforms

| Platform       | File                                    | Trigger                        |
|----------------|-----------------------------------------|-------------------------------|
| GitHub Actions | `ci/github-actions/radea-debug.yml`     | workflow failure               |
|                | `ci/github-actions/radea-iac-review.yml`| PR with `.tf` changes          |
| GitLab CI      | `ci/gitlab-ci/radea.gitlab-ci.yml`      | stage failure / MR with `.tf`  |
| Jenkins        | `ci/jenkins/Jenkinsfile`                | post-failure / `.tf` changeset |
| CircleCI       | `ci/circleci/config.yml`                | workflow failure / PR          |
| Azure DevOps   | `ci/azure-devops/radea-pipeline.yml`    | stage failure / PR             |
| Bitbucket      | `ci/bitbucket/bitbucket-pipelines.yml`  | default / pull-request         |
| Drone CI       | `ci/drone/drone.yml`                    | step failure / pull_request    |

---

## GitHub Actions

**1. Copy the workflow files:**
```
.github/workflows/radea-debug.yml
.github/workflows/radea-iac-review.yml
```

**2. Add secret:**
```
Settings -> Secrets and variables -> Actions -> New repository secret
Name: OPENAI_API_KEY
```

**3. Change one line** in `radea-debug.yml` to match your main workflow name:
```yaml
workflows: ["CI"]   # <- your workflow name here
```

That is it. Your existing CI is untouched.

**What appears in the PR:**

```
## RADEA Build Triage — AI DRAFT
> Verify every item before acting.

Failure type: `dependency_drift`

| # | Cause | Confidence | Description | Verify |
|---|-------|-----------|-------------|--------|
| 1 | Package version bump | high | axios bumped 1.x->2.x breaking import | `git log --oneline package-lock.json \| head -5` |
| 2 | Base image updated  | medium | node:20 removed deprecated API | `docker inspect node:20 \| grep Created` |

*Sanitizer: 2 redaction(s) applied.*
```

---

## GitLab CI

**1. Copy the file:**
```
ci/radea.gitlab-ci.yml
```

**2. Add to your `.gitlab-ci.yml`:**
```yaml
include:
  - local: ci/radea.gitlab-ci.yml
```

**3. Add variable:**
```
Settings -> CI/CD -> Variables
Key: OPENAI_API_KEY   Masked: yes   Protected: yes
```

---

## Jenkins

**1. Add credential:**
```
Manage Jenkins -> Credentials -> Global -> Add
Kind: Secret text   ID: openai-api-key
```

**2. Paste the two blocks** from `ci/jenkins/Jenkinsfile` into your existing Jenkinsfile:
- The `RADEA IaC Review` stage (runs when `.tf` files change)
- The `post { failure { ... } }` block (runs on any failure)

---

## Azure DevOps

**1. Add variable:**
```
Pipeline -> Variables -> OPENAI_API_KEY   (lock icon: secret)
```

**2. Copy** `ci/azure-devops/radea-pipeline.yml` or merge the two RADEA stages into your existing pipeline YAML.

---

## CircleCI, Bitbucket, Drone

Copy the relevant file from `ci/` and set the `OPENAI_API_KEY` environment variable
in your repository settings. Each file has a comment at the top explaining exactly where.

---

## Local usage (no CI required)

```bash
# Triage a failed build
radea debug --log ./ci.log

# Review Terraform before apply
terraform plan -out=plan.tfplan
terraform show -json plan.tfplan > plan.json
radea iac-review --file main.tf --plan plan.json

# Compress incident logs
radea triage --logs ./incident-logs/ --metrics metrics.json
```

---

## Environment variables

| Variable              | Description                        | Default           |
|-----------------------|------------------------------------|-------------------|
| `OPENAI_API_KEY`      | OpenAI API key                     | —                 |
| `RADEA_MODEL`         | Model to use                       | `openai/gpt-4o`   |
| `RADEA_LOCAL`         | Route via Ollama (no cloud)        | `false`           |
| `RADEA_SANITIZE`      | Strip secrets before sending       | `true`            |
| `RADEA_MAX_LOG_CHARS` | Max characters sent per request    | `32000`           |
| `RADEA_OLLAMA_URL`    | Ollama base URL                    | `http://localhost:11434` |
