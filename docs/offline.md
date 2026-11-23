# Offline engines for small runners

From 0.2.0rc1, `RADEA_MODEL=offline` is the default. The rule set recognises 36 failure
signatures (CI, container, Kubernetes, Helm, registry, Git and Terraform failures); symptoms
such as CrashLoopBackOff or a failed probe are reported but never decide the category. Available cloud credentials do
not activate remote inference. Base installation excludes OpenAI/Anthropic/Google
SDKs and ML frameworks. All three analysis commands run without a model server,
GPU, inference network connection, artifact download or API key.

```sh
python -m pip install .
radea debug --log examples/logs/failed-build.log --output json
radea iac-review --plan examples/evaluation/delete-plan.json --output json
radea triage --logs examples/logs/incident.log --output json
```

| Engine | Work performed locally | Selection |
| --- | --- | --- |
| Rules (default) | Known error signals, evidence-linked templates, plan/IAM checks, log patterns/timestamps, supplied metric differences | `RADEA_MODEL=offline` |
| Linear classifier | Same rules plus an experimental debug category hint; 128 hashed features, five linear outputs | `RADEA_MODEL=offline-linear` |
| Micro neural network | Same rules plus an experimental debug category hint; 128 inputs, eight tanh hidden units, five outputs | `RADEA_MODEL=offline-neural` |
| Provider adapter | Explicit remote/served model request through existing evidence guardrails | E.g. `RADEA_MODEL=openai/<model-id>` and `pip install '.[openai]'` |

No engine applies changes or runs suggested commands. Terraform `policy-check`
remains the blocking gate; advisory findings do not imply authorization.
`--local` retains its older meaning of forcing loopback Ollama; it is not required
for offline rules and will select Ollama instead. For offline operation, leave it off.
An injected ModelClient remains an explicit application integration, not an offline guarantee.

Rules identify signals, not proven causes. Conflicting categories and unfamiliar
messages remain `unknown`. Triage counts matching **retained evidence lines**, not
all events in the original file; one line can match several patterns. Timestamps
are copied in source order, not timezone-normalized into a global chronology.
Partial input carries an incompleteness warning. IAM scanning checks literal
wildcards only. Neither an empty finding list nor a valid citation proves safety.

Results carry `analysis_origin=deterministic_rules`, `analysis_version`, evidence IDs,
source hashes and draft status. Offline human-facing output says OFFLINE DRAFT.
`classifier_hint` is separate from the rule category. Margins are not calibrated
probabilities; low margins abstain to unknown. Models cannot suppress rule findings,
change causes, claim verified conclusions or override destructive-action gates.
Weights are bundled bounded numeric JSON with fixed shapes, never executable pickle.

## Reproduced examples and comparison

[corpus.json](../examples/offline/corpus.json) contains 20 actual stderr captures
from intentionally failing local Python processes, each with its reproducer,
category, family and origin. Interpreter installation paths are normalized.
This is a small reproducible engineering corpus, **not real production incident logs**.
The categories describe observable failure types; they do not establish an incident cause.

Ten cases train the classifiers, five select the abstention threshold, and five
form the test partition. Reproducer families never cross partitions. Familiar
exception signatures can recur across families: this is not a generalization proof.
Rules are hand-authored and evaluated as regression behavior, not a blind learned
baseline. Test results were inspected during development; a future production
benchmark needs a fresh, independently labeled holdout.

Current recorded result in [offline-comparison.json](offline-comparison.json):

| Engine | Test correct / 5 | Macro F1 | Weight bytes |
| --- | --- | --- | --- |
| Rules | 4 | 0.733 | None |
| Linear | 3 | 0.500 | 13,300 |
| Micro neural | 3 | 0.600 | 22,220 |

Five test cases are too few for a production accuracy claim. There is no evidence
here that either classifier improves on the rules; both stay experimental opt-ins.
Keep the rule default. Before adopting a hint, collect consented, anonymized incident
examples, have engineers label them, partition by incident/project/time, freeze a
new holdout and review false positives, missed risks and abstentions per category.
Do not upload private incident logs to this public repository.

Training is a developer action, outside the runtime and CI runner:

```sh
# POSIX developer machine; reproduces known failures, without network access.
python tools/build_offline_corpus.py
PYTHONPATH=src python tools/compare_offline_models.py --train
# Evaluation only: does not train or rewrite bundled weights.
PYTHONPATH=src python tools/compare_offline_models.py --output /tmp/comparison.json
```

Training uses a fixed seed, 250 epochs and a shared input representation; model
thresholds use calibration data only. The artifacts record the corpus hash.
Reproduction across Python versions can change traceback text and therefore model
weights; committed data/weights are the fixed reference for this comparison.

## Resources and delivery

The complete debug pipeline over a 6 MiB log measured about 28 MiB peak process RSS
and 2.7 seconds locally on macOS. This includes evidence collection and sanitization,
not just classification. These local runs did not enforce resource limits.
CI benchmarks each engine in a separate Linux process with one CPU, 256 MiB address
space, a 30-second CPU budget and a peak RSS assertion below 128 MiB. CI also verifies
all three commands from an installed wheel without the OpenAI SDK present.

```sh
PYTHONPATH=src python tools/benchmark_runner.py --model offline
PYTHONPATH=src python tools/benchmark_runner.py --model offline-linear
PYTHONPATH=src python tools/benchmark_runner.py --model offline-neural
```

Read the CI distribution artifacts for actual constrained measurements and the
comparison JSON for the confusion matrices and tiny inference batch timings. Those
short batch timings are observations, not statistically reliable speed rankings.
The reported comparison-process RSS includes all engines; the three separate
pipeline benchmark reports are the per-process resource checks.

## Why no new neural network was trained

The bundled linear and micro neural classifiers stay experimental opt-ins. After the rule set
grew from 8 to 36 signatures the recorded comparison is unchanged (rules 4/5, linear 3/5,
neural 3/5), because the 20-case corpus contains only Python exceptions. Training another
model on ten examples would produce a convincing number and no real capability, while rules
are inspectable, deterministic and already cover far more failure types. A model is worth
adding only after consented, independently labelled incident logs exist (see above).

## Measured resource use

No GPU and no network. Start-up 0.08 s / 17 MB; a 3 MB, 40,000-line log through `debug`
3 s / 29 MB; 2,000 Deployments through `k8s-review` 2.2 s / 59 MB; a 5,000-resource Terraform
file through `tf-review` 0.6 s / 34 MB (single laptop-class core). The regression tests keep
hostile 64 KiB lines under a second.

