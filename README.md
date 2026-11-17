# RADEA — Reliable AI-Driven Engineering Automation

AI drafts. You decide. Every time.

RADEA is a Python CLI for CI failure analysis, Terraform review and incident log
summaries. It drafts recommendations; it does not execute suggested commands or
apply infrastructure changes. Model responses require human review.

## Install

Requires Python 3.10+. From a source checkout:

```sh
git clone https://github.com/CloudOpsMaster/radea.git
cd radea
python -m pip install .
radea --help
```

## Quick start without credentials

```sh
radea debug --log examples/logs/failed-build.log --dry-run
radea iac-review --file examples/terraform/main.tf --dry-run
radea triage --logs examples/logs/incident.log --dry-run
```

Dry run sanitizes input and displays a preview without contacting any model.
It does not perform AI analysis.

## Models and runners without GPUs

RADEA itself does not load model weights or require a GPU. On a small CI runner,
use a cloud API or Kiro CLI: inference happens remotely. Network access and valid
provider authentication are required. Usage limits and charges belong to the
selected provider. Unknown provider prefixes fail; there is no automatic provider fallback.

| Selection (`RADEA_MODEL`) | Authentication | Inference |
| --- | --- | --- |
| `openai/<model-id>` | `OPENAI_API_KEY` | Cloud |
| `anthropic/<model-id>` | `ANTHROPIC_API_KEY`; install `.[anthropic]` | Cloud |
| `google/<model-id>` | `GOOGLE_API_KEY`; install `.[google]` | Cloud |
| `kiro` or `kiro/<model-id>` | Installed, authenticated `kiro-cli` | Kiro service |
| `ollama/<model-id>` | Running Ollama server with model installed | Configured server |

Model IDs must be available in your provider account. `openai/gpt-4o` is the
current application default; an unprefixed model name selects OpenAI.

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
export RADEA_MODEL=ollama/llama3.2
radea debug --log examples/logs/failed-build.log --local
```

`--local` or `RADEA_LOCAL=true` forces Ollama. If the selected model is not an
Ollama model, it uses `llama3.2`. `RADEA_OLLAMA_URL` defaults to
`http://localhost:11434`. Local CPU inference is possible but needs sufficient
RAM and can be slow. A remote Ollama URL requires HTTPS and explicit
`RADEA_ALLOW_REMOTE_OLLAMA=true`. `--local` rejects non-loopback endpoints. Use cloud
inference for constrained runners; use dry run for completely offline previews.

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

Sanitization detects common AWS credentials, GitHub tokens, authorization headers,
private keys, URL passwords and long secret assignments. It is best effort:
review inputs before sending sensitive material. Common internal hostnames, private
IPv4 addresses and emails use stable request-local placeholders (up to 1,024 aliases,
then a generic placeholder). Detection of every sensitive value is not guaranteed.
`debug --no-sanitize` is rejected; remote and local input paths require redaction.
Terraform context and incident metrics are also sanitized.

## Python API

```python
from radea.api import AnalysisRequest, analyze

result = analyze(AnalysisRequest(command="debug", paths=("ci.log",)))
```

The API returns data without printing. Reuse `AnalysisService` for explicit configuration
and an injectable model transport; every adapter uses the same guardrails.
See [architecture and integration examples](docs/architecture.md) and the
[complete 60-article feature matrix](docs/feature-matrix.uk.md).

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
