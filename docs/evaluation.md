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

## Matched pilot report

```json
{"cases":[{"id":"paired-case-1","baseline_minutes":20,"assisted_minutes":8,"verification_minutes":4,"rework_minutes":2,"accepted":true,"missed_critical":false}]}
```

`radea pilot-report cases.json` sums assisted execution, review and rework, then compares
that total with the measured baseline. It reports net time saved, median paired savings,
speedup, acceptance and critical misses. Record rejected cases too and include the time spent
finishing or correcting them. This report describes the supplied sample; team-wide claims
require a representative pilot with comparable tasks and consistent review criteria.

To report cost-adjusted ROI, include an `economics` object with `currency` and
decimal-string amounts for `hourly_labor_rate`, `licenses`, `api_compute`,
`adoption`, and `incident_cost`. Use one currency and allocate costs to the same
measurement period. The report subtracts assisted labor and additional expenses
from baseline labor value. ROI is that net value divided by assisted labor and
additional expenses, expressed as a percentage. The report leaves ROI null when
the investment is zero. Review quality, sentiment and delivery metrics separately.

## Team adoption playbook

1. Pick a recurring task with a measurable bottleneck. For a first pilot, use CI failure
   triage, Terraform plan review, or Kubernetes manifest review. Assign an owner and a
   reviewer, then record how the team handles the task today.
2. Collect matched baseline and assisted cases. Prefer local processing for new workflows.
   Before enabling a remote provider, decide which inputs it may receive and verify the
   redacted payload with a dry run.
3. Require verification at the same point in both runs. For CI triage, reproduce the failure
   and review the cited log evidence. For infrastructure, run the deterministic checks and
   verify the actual plan or rendered manifests before applying a change.
4. Record assisted execution, review, rework, critical misses, and whether the reviewer
   accepted the result. Run `radea pilot-report` and discuss both accepted and rejected cases.
5. Decide which task patterns to adopt, revise, or retire. Assign someone to update the
   playbook when a prompt, provider, input policy, or verification requirement changes.

### Practice manual review and handoff

- **Article 1. Advisory CI triage.** Run `RADEA_MODEL=offline radea debug --log
  examples/logs/failed-build.log --output json`. Check the draft and its cited
  evidence. The reviewer verifies the hypothesis before acting. The offline
  regression test checks model and network isolation and unverified conclusions.
- **Article 25. Documentation alongside code.** After changing a CLI command or
  static rule, update the README and the relevant guide. Run
  `python tools/gen_rules_doc.py` for rule changes and `python -m pytest tests/test_docs.py`
  to verify the generated reference, command inventory and article links in rules.
- **Article 30. Modernization decision.** Write down the current operational
  problem, cost of keeping the system, smallest reversible intervention and its
  stop condition. Retain the current system when the expected benefit fails to justify
  the migration. If proceeding, use `cutover-plan --fail-at STEP` to test that the
  draft stops and rolls back the steps already applied. See [cutover rehearsal](static-review.md#cutover-rehearsal).
- **Articles 44 and 48. Incident ownership.** Run `triage` against the incident
  input, verify the evidence and nominate a human incident owner. Record the
  conclusion, evidence and follow-up owners with `postmortem-review`. In the
  handoff, name the person who can approve a mitigation and leave the cause
  open if it has yet to be confirmed. See [postmortem review](static-review.md#human-review-of-a-postmortem).
- **Article 50. Productivity calibration.** Run the matched pilot above using
  comparable tasks. A baseline of 20 minutes and assisted effort of 8 minutes plus
  4 minutes of verification and 2 of rework yields 6 minutes saved and roughly
  1.43× speedup for that sample. Keep rejected cases in the sample and use
  the measured distribution and critical misses when deciding where to adopt the tool.

### Prompts for a pilot

- CI failure. “Use only the supplied log evidence. Give the probable failure category,
  supporting line IDs, and one command I can use to verify the hypothesis. Mark missing
  evidence and do not claim a root cause without proof.”
- Infrastructure. “Use only the supplied plan or manifest. Identify the relevant resource
  and field for each concern. Keep verified deterministic findings distinct from hypotheses
  and state how to confirm each hypothesis.”
- Incident review. “Draft a timeline from timestamped evidence. Keep the cause and impact
  uncertain where evidence is incomplete. List information the on-call engineer can collect
  to confirm or reject each hypothesis.”
