# Evaluation and adoption

Passing unit tests proves specified software behavior. It does not certify the
accuracy of OpenAI, Anthropic, Gemini, Ollama or Kiro on your infrastructure.

The synthetic starter corpus in `examples/evaluation/cases.json` covers dependency
failure, database destruction and incident timeouts. It contains no customer logs.
Add human-reviewed, anonymized cases from your own environment before a team pilot.
Record expected risk findings, real evidence, acceptable uncertainty and rejected
claims; assign an engineer to review every reference answer.

Generate outputs explicitly with your selected authenticated backend, for example:

```sh
mkdir -p /tmp/radea-evaluation
radea debug --log examples/logs/failed-build.log --output json > /tmp/radea-evaluation/missing-module.json
radea iac-review --plan examples/evaluation/delete-plan.json --output json > /tmp/radea-evaluation/database-delete.json
radea triage --logs examples/logs/incident.log --output json > /tmp/radea-evaluation/database-timeouts.json
python -m radea.evaluation --cases examples/evaluation/cases.json --responses /tmp/radea-evaluation
```

These commands use local rules by default. Explicit provider selections call that
service and consume its quota; dry-run cannot measure model quality. The evaluation scorer itself makes no network calls.
It reports missing outputs, invalid contracts, missed/extra destructive resources
and category matches. A valid citation only proves membership in supplied evidence;
false causal claims still require human scoring.

For a bounded pilot record model/provider, tool version, prompt hash, inputs hash,
review time, corrected claims, missed risks and whether the engineer accepted the
draft. Compare total task + verification time with a non-AI baseline. Do not claim
1.3x productivity, lower incident MTTR or production accuracy without those measurements.
Do not use AI ranking to hide deterministic critical findings.

Mocked SDK/process tests and the local fake executable are contract tests, not live
provider validation. Run an explicit smoke test of your installed Kiro version and
headless authentication before adopting it. Kiro model IDs and service aliases remain
provider-controlled; record the effective model/version when available.

The separate [offline comparison](offline.md) uses locally reproduced process failures
and fixed family partitions, with bundled linear/MLP weights. It is a small engineering
comparison, not a production incident accuracy claim.
