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
selected provider. No automatic provider fallback sends data elsewhere.

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
RAM and can be slow. A remote Ollama URL sends data to that server. Use cloud
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
use text output. `post-comment` writes to GitHub/GitLab when configured; otherwise
it prints Markdown. See [CI integration](docs/ci-integration.md).

Configuration uses environment variables; there is no `radea config` command.
`RADEA_MAX_LOG_CHARS` defaults to 32,000. There is currently no persisted audit log.
The baseline value is supplied to the model alongside metrics; RADEA does not
fetch historical metrics or independently calculate anomalies.

## Data handling

Sanitization detects common AWS credentials, GitHub tokens, authorization headers,
private keys, URL passwords and long secret assignments. It is best effort:
review inputs before sending sensitive material. It does not anonymize hostnames
or guarantee detection of every secret. `debug --no-sanitize` disables redaction
explicitly. Terraform context and incident metrics are also sanitized.

## Development and release

```sh
python -m pip install -e '.[dev]'
python -m pytest
ruff check src tests
```

The shared CI runs tests on Python 3.10–3.12, lint, dependency vulnerability
scanning, static security analysis, distribution validation and an installed-wheel
smoke test. It runs on pull requests and pushes to main, and is reused before tag
releases. Security unit tests run with the ordinary Python suite; dependency and
static scans are separate steps in the same CI workflow.

Branch protection must be configured in GitHub to require these jobs. Workflow
files alone do not block merging. The manual demo uses dry run without API keys.
Tag releases build a wheel and attach it to a GitHub Release; they do not publish
to PyPI. Automated tests mock model calls and consume no inference credits.

See [contributing](CONTRIBUTING.md) and [security policy](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
