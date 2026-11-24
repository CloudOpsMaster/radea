import json
from hashlib import sha256

from click.testing import CliRunner

from radea.cli import main

GITLAB = """\
stages: [build, test]
build:
  stage: build
  script: ["echo building"]
verify:
  stage: test
  script: ["echo verifying"]
independent:
  stage: test
  needs: []
  script: ["echo checking"]
"""


def test_translate_then_compare_job_dependencies(tmp_path):
    source = tmp_path / "gitlab.yml"
    source.write_text(GITLAB)
    runner = CliRunner()
    translation = runner.invoke(main, ["ci-translate", str(source)])
    assert translation.exit_code == 0, translation.output
    workflow = json.loads(translation.output)
    assert workflow["on"] == {"workflow_dispatch": {}}
    assert workflow["jobs"]["verify"]["needs"] == ["build"]
    assert "needs" not in workflow["jobs"]["independent"]
    target = tmp_path / "github.yml"
    target.write_text(translation.output)
    difference = runner.invoke(main, ["ci-diff", str(source), str(target), "--fail-on-change"])
    assert difference.exit_code == 0, difference.output
    assert json.loads(difference.output)["modified"] == []
    workflow["jobs"]["verify"].pop("needs")
    target.write_text(json.dumps(workflow))
    difference = runner.invoke(main, ["ci-diff", str(source), str(target), "--fail-on-change"])
    assert difference.exit_code == 2
    assert json.loads(difference.output)["modified"][0]["name"] == "verify"


def test_translate_github_preserves_needs_and_gates_unsupported_jobs(tmp_path):
    runner = CliRunner()
    source = runner.invoke(main, ["ci-translate", "-"], input=GITLAB)
    assert source.exit_code == 0, source.output
    workflow = tmp_path / "github.yml"
    workflow.write_text(source.output)
    image = "docker.io/library/ubuntu@sha256:" + "a" * 64
    args = ["ci-translate", str(workflow), "--from-platform", "github", "--image", image]
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    translated = json.loads(result.output)
    assert translated["workflow"] == {"rules": [{"if": '$CI_PIPELINE_SOURCE == "web"'}]}
    assert translated["verify"]["needs"] == [{"job": "build", "artifacts": False}]
    assert translated["independent"]["needs"] == []
    assert translated["verify"]["image"] == image
    assert translated["verify"]["timeout"] == "30 minutes"
    assert translated["verify"]["script"] == ["set -eo pipefail\necho verifying"]
    target = tmp_path / "gitlab.yml"
    target.write_text(result.output)
    result = runner.invoke(main, ["ci-diff", str(workflow), str(target), "--fail-on-change"])
    assert result.exit_code == 0, result.output
    workflow.write_text(source.output.replace("echo verifying", "echo $GITHUB_SHA"))
    result = runner.invoke(main, args)
    assert result.exit_code == 1
    assert "GitHub-specific expression" in result.output


def test_pipeline_cycle_and_unsupported_translation():
    runner = CliRunner()
    cycle = GITLAB.replace("stage: build", "stage: build\n  needs: [verify]", 1)
    result = runner.invoke(main, ["ci-graph", "-"], input=cycle)
    assert result.exit_code == 1
    assert "cycle" in result.output
    for command in ("echo ${{ github.token }}", "echo $CI_JOB_ID"):
        result = runner.invoke(
            main, ["ci-translate", "-"], input=GITLAB.replace("echo building", command)
        )
        assert result.exit_code == 1
        assert "platform-specific" in result.output


def test_ci_diff_gate_handles_unresolved_dependencies(tmp_path):
    unresolved = """\
include: remote.yml
build:
  needs: [external]
  script: ['echo hello']
"""
    path = tmp_path / "gitlab.yml"
    path.write_text(unresolved)
    result = CliRunner().invoke(
        main, ["ci-diff", str(path), "-", "--fail-on-change"], input=unresolved
    )
    assert result.exit_code == 2
    report = json.loads(result.output)
    assert report["partial"] is True
    assert report["before"]["unresolved_needs"] == ["external"]


def test_drift_ignores_runtime_defaults_and_tracks_declared_fields(tmp_path):
    desired = tmp_path / "desired.yaml"
    desired.write_text(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: demo, namespace: lab}\n"
        "spec: {replicas: 2}\n"
    )
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "demo", "namespace": "lab", "resourceVersion": "9"},
        "spec": {"replicas": 2, "revisionHistoryLimit": 10},
        "status": {"readyReplicas": 1},
    }
    observed = {"apiVersion": "v1", "kind": "List", "items": [deployment]}
    runner = CliRunner()
    args = ["k8s-drift", str(desired), "-", "--fail-on-drift"]
    result = runner.invoke(main, args, input=json.dumps(observed))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["changes"] == []
    deployment["spec"]["replicas"] = 3
    result = runner.invoke(main, args, input=json.dumps(observed))
    assert result.exit_code == 2
    assert json.loads(result.output)["changes"][0]["fields"] == ["spec"]


def test_k8s_health_reports_structured_symptoms_without_messages():
    pod = {
        "kind": "Pod",
        "metadata": {"namespace": "lab", "name": "app"},
        "status": {
            "phase": "Running",
            "conditions": [{"type": "Ready", "status": "False"}],
            "containerStatuses": [
                {
                    "name": "web",
                    "restartCount": 3,
                    "state": {
                        "waiting": {
                            "reason": "CrashLoopBackOff",
                            "message": "private context",
                        }
                    },
                    "lastState": {"terminated": {"reason": "OOMKilled"}},
                }
            ],
        },
    }
    result = CliRunner().invoke(
        main,
        ["k8s-health", "-", "--fail-on-signal"],
        input=json.dumps({"kind": "PodList", "items": [pod]}),
    )
    assert result.exit_code == 2
    assert "private context" not in result.output
    report = json.loads(result.output)
    assert report["summary"] == {"pods": 1, "signals": 3}
    assert report["pods"][0]["restarts"] == 3
    assert {signal["reason"] for signal in report["pods"][0]["signals"]} == {
        "PodNotReady",
        "CrashLoopBackOff",
        "OOMKilled",
    }


def test_terraform_refresh_drift_is_distinct_from_planned_changes(tmp_path):
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "format_version": "1.2",
                "resource_changes": [
                    {"address": "demo.planned", "change": {"actions": ["create"]}}
                ],
                "resource_drift": [
                    {
                        "address": "demo.drift",
                        "change": {"actions": ["update"], "before": {"token": "private-value"}},
                    }
                ],
            }
        )
    )
    result = CliRunner().invoke(main, ["tf-drift", str(plan), "--fail-on-drift"])
    assert result.exit_code == 2, result.output
    assert "private-value" not in result.output
    assert json.loads(result.output)["drift"] == [{"address": "demo.drift", "action": "update"}]


def test_metric_anomalies_uses_recent_readings_and_relative_floor():
    metrics = {
        "series": {
            "cost": {"history": [900, 100, 100, 101, 100, 100], "current": 120},
            "traffic": {"history": [100] * 5, "current": 104},
        }
    }
    result = CliRunner().invoke(
        main,
        ["metric-anomalies", "-", "--window", "5", "--fail-on-anomaly"],
        input=json.dumps(metrics),
    )
    assert result.exit_code == 2, result.output
    cost, traffic = json.loads(result.output)["metrics"]
    assert cost["baseline_median"] == 100
    assert cost["anomaly"] is True
    assert traffic["anomaly"] is False


def test_pilot_report_counts_rework_and_keeps_rejected_cases():
    cases = {
        "cases": [
            {
                "id": "one",
                "baseline_minutes": 20,
                "assisted_minutes": 6,
                "verification_minutes": 4,
                "rework_minutes": 0,
                "accepted": True,
                "missed_critical": False,
            },
            {
                "id": "two",
                "baseline_minutes": 10,
                "assisted_minutes": 6,
                "verification_minutes": 5,
                "rework_minutes": 4,
                "accepted": False,
                "missed_critical": True,
            },
        ]
    }
    result = CliRunner().invoke(main, ["pilot-report", "-"], input=json.dumps(cases))
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["assisted_total_minutes"] == 25
    assert report["net_minutes_saved"] == 5
    assert report["accepted"] == 1
    assert report["missed_critical"] == 1
    cases["economics"] = {
        "currency": "USD", "hourly_labor_rate": "60", "licenses": "2",
        "api_compute": "1", "adoption": "3", "incident_cost": "0",
    }
    result = CliRunner().invoke(main, ["pilot-report", "-"], input=json.dumps(cases))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["economics"] == {
        "currency": "USD", "baseline_labor": "30.00", "assisted_labor": "25.00",
        "additional_costs": "6.00", "net_value": "-1.00", "roi_percentage": "-3.23",
    }


def test_ci_observe_emits_opening_and_recovery_without_log_payload(tmp_path, monkeypatch):
    log = tmp_path / "run.log"
    log.write_text("OOMKilled raw-private-log\nOOMKilled raw-private-log\n")
    cycle = 0

    def poll(seconds):
        nonlocal cycle
        assert seconds == 1
        cycle += 1
        if cycle == 2:
            log.write_text("Build succeeded\n")
        if cycle == 3:
            raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", poll)
    result = CliRunner().invoke(main, [
        "ci-observe", str(log), "--threshold", "2", "--watch", "1",
    ])
    assert "raw-private-log" not in result.output
    assert [json.loads(line)["event"] for line in result.stdout.splitlines()] == [
        "opened", "recovered",
    ]


def test_threat_review_covers_stride_and_honors_verified_controls():
    model = {
        "components": [{"id": "user", "zone": "outside"}, {"id": "api", "zone": "app"}],
        "flows": [{"id": "write", "from": "user", "to": "api", "writes": True}],
    }
    runner = CliRunner()
    args = ["threat-review", "-", "--output", "json"]
    result = runner.invoke(main, args, input=json.dumps(model))
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert report["draft"] is True
    assert {item["rule"] for item in report["findings"]} == {f"TH{n:03d}" for n in range(1, 7)}
    assert all(item["target"] == "write" for item in report["findings"])

    model["flows"][0]["controls"] = {"authenticated": True, "encrypted": True}
    result = runner.invoke(main, args, input=json.dumps(model))
    findings = json.loads(result.output)["findings"]
    assert {item["rule"] for item in findings} == {"TH002", "TH003", "TH005", "TH006"}

    model["flows"][0]["to"] = "unknown"
    result = runner.invoke(main, args, input=json.dumps(model))
    assert result.exit_code == 1


def test_threat_dispositions_are_bound_to_the_exact_draft(tmp_path):
    model = {
        "components": [{"id": "user", "zone": "outside"}, {"id": "api", "zone": "app"}],
        "flows": [{"id": "submit", "from": "user", "to": "api"}],
    }
    runner = CliRunner()
    result = runner.invoke(
        main, ["threat-review", "-", "--output", "json"], input=json.dumps(model),
    )
    draft = tmp_path / "draft.json"
    draft.write_text(result.output)
    decisions = {"draft_sha256": sha256(draft.read_bytes()).hexdigest(), "decisions": []}
    args = ["threat-disposition", str(draft), "-", "--require-complete"]
    result = runner.invoke(main, args, input=json.dumps(decisions))
    assert result.exit_code == 2, result.output
    pending = json.loads(result.output)["pending"]
    assert pending
    decisions["decisions"] = [
        {**item, "status": "mitigate", "owner": "platform", "reason": "Add reviewable controls"}
        for item in pending
    ]
    result = runner.invoke(main, args, input=json.dumps(decisions))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["pending"] == []
    draft.write_text(draft.read_text() + "\n")
    assert runner.invoke(main, args, input=json.dumps(decisions)).exit_code == 1


def test_telemetry_review_correlates_logs_and_exemplars(tmp_path):
    trace = "a" * 32
    other = "b" * 32
    span = {
        "traceId": trace.upper(),
        "spanId": "a" * 16,
        "parentSpanId": "b" * 16,
        "startTimeUnixNano": "1000000",
        "endTimeUnixNano": 3000000,
        "status": {"code": 2, "message": "private-span-message"},
    }
    batch = {"resourceSpans": [{"scopeSpans": [{"spans": [span]}]}]}
    traces = tmp_path / "traces.jsonl"
    traces.write_text(json.dumps(batch) + "\n" + json.dumps(batch))
    logs = tmp_path / "logs.json"
    records = [
        {"traceId": trace, "severityNumber": 17, "body": {"stringValue": "private-log-body"}},
        {"traceId": other, "severityNumber": 9},
        {},
    ]
    logs.write_text(json.dumps({"resourceLogs": [{"scopeLogs": [{"logRecords": records}]}]}))
    metrics = tmp_path / "metrics.json"
    points = [{"exemplars": [{"traceId": trace}, {"traceId": other}]}]
    metric = {"histogram": {"dataPoints": points}}
    metrics.write_text(json.dumps({"resourceMetrics": [{"scopeMetrics": [{"metrics": [metric]}]}]}))
    result = CliRunner().invoke(
        main, ["telemetry-review", str(traces), "--logs", str(logs), "--metrics", str(metrics)]
    )
    assert result.exit_code == 0, result.output
    assert "private-" not in result.output
    report = json.loads(result.output)
    assert report["traces"] == [
        {
            "trace_id": trace,
            "span_count": 1,
            "error_spans": 1,
            "missing_parent_spans": 1,
            "observed_span_window_ms": 2,
            "logs": 1,
            "error_logs": 1,
            "metric_exemplars": 1,
        }
    ]
    assert report["logs_without_trace_id"] == 1
    assert report["logs_without_matching_trace"] == 1
    assert report["exemplars_without_matching_trace"] == 1


def test_dora_report_filters_window_and_deduplicates_delivered_changes():
    def change(name):
        return {"id": name, "committed_at": "2026-01-01T00:00:00Z"}

    def deployment(name, time, *, failed=False, rework=False, changes=(), recovered=None):
        return {
            "id": name,
            "service": "api",
            "deployed_at": time,
            "failed": failed,
            "rework": rework,
            "changes": list(changes),
            "recovered_at": recovered,
        }

    events = {
        "window": {"start": "2026-01-02T00:00:00Z", "end": "2026-01-03T00:00:00Z"},
        "deployments": [
            deployment("previous", "2026-01-01T12:00:00Z", changes=[change("old")]),
            deployment(
                "broken",
                "2026-01-02T01:00:00Z",
                failed=True,
                recovered="2026-01-02T01:30:00Z",
                changes=[change("new")],
            ),
            deployment(
                "fix", "2026-01-02T02:00:00Z", rework=True, changes=[change("new"), change("old")]
            ),
            deployment("next-window", "2026-01-03T00:00:00Z"),
        ],
    }
    result = CliRunner().invoke(main, ["dora-report", "-"], input=json.dumps(events))
    assert result.exit_code == 0, result.output
    (service,) = json.loads(result.output)["services"]
    assert service["deployments_per_day"] == 2
    assert service["change_lead_time_samples"] == 1
    assert service["change_lead_time_median_seconds"] == 26 * 3600
    assert service["change_fail_rate"] == 0.5
    assert service["deployment_rework_rate"] == 0.5
    assert service["failed_deployment_recovery_median_seconds"] == 1800


def test_iam_simulation_gate_uses_per_resource_decisions_and_fails_unknown(tmp_path):
    results = tmp_path / "simulation.json"
    results.write_text(json.dumps({"EvaluationResults": [{
        "EvalActionName": "s3:GetObject", "EvalDecision": "implicitDeny",
        "ResourceSpecificResults": [
            {"EvalResourceName": "arn:aws:s3:::example/allowed", "EvalResourceDecision": "allowed"},
            {
                "EvalResourceName": "arn:aws:s3:::example/denied",
                "EvalResourceDecision": "explicitDeny",
            },
            {
                "EvalResourceName": "arn:aws:s3:::example/unknown",
                "EvalResourceDecision": "implicitDeny",
                "MissingContextValues": ["aws:PrincipalTag/team"],
            },
        ],
    }]}))
    cases = [
        {"action": "s3:GetObject", "resource": f"arn:aws:s3:::example/{name}", "expect": expected}
        for name, expected in [("allowed", "allow"), ("denied", "deny"), ("unknown", "deny")]
    ]
    args = ["iam-simulation-review", str(results), "-", "--fail-on-mismatch"]
    result = CliRunner().invoke(main, args, input=json.dumps(cases))
    assert result.exit_code == 2, result.output
    assert [case["simulated"] for case in json.loads(result.output)["cases"]] == [
        "allowed", "explicitDeny", "unknown",
    ]
    assert CliRunner().invoke(main, args, input=json.dumps(cases[:2])).exit_code == 0


def test_rebuild_check_reports_inventory_drift_without_values(tmp_path):
    original = tmp_path / "original.json"
    original.write_text(json.dumps({
        "packages": {"example": "sensitive-baseline-version"},
        "services": {"example.service": "enabled,active"},
        "probes": {"readiness": "200"},
    }))
    candidate = {
        "packages": {"example": "sensitive-candidate-version"}, "probes": {"readiness": "200"},
    }
    args = ["rebuild-check", str(original), "-", "--fail-on-change"]
    runner = CliRunner()
    result = runner.invoke(main, args, input=json.dumps(candidate))
    assert result.exit_code == 2, result.output
    assert "sensitive-" not in result.output
    report = json.loads(result.output)
    assert report["missing_categories"] == ["services"]
    assert report["changes"][0] == {"category": "packages", "name": "example", "change": "changed"}
    result = runner.invoke(main, args, input=original.read_text())
    assert result.exit_code == 0, result.output


def test_tf_plan_diff_compares_resource_values_without_printing_them(tmp_path):
    baseline, candidate = (tmp_path / name for name in ("old.json", "new.json"))
    data = {
        "format_version": "1.2", "resource_changes": [{
            "address": "terraform_data.test",
            "change": {"actions": ["no-op"], "after": {"private-key-name": True}},
        }],
    }
    baseline.write_text(json.dumps(data))
    data["resource_changes"][0]["change"]["after"]["private-key-name"] = 1
    candidate.write_text(json.dumps(data))
    result = CliRunner().invoke(main, [
        "tf-plan-diff", str(baseline), str(candidate), "--fail-on-change",
    ])
    assert result.exit_code == 2, result.output
    assert "private-key-name" not in result.output
    assert json.loads(result.output)["changes"][0]["changed_fields"] == 1


def test_repository_contract_gate_detects_missing_and_mismatched_revisions(tmp_path):
    provider = tmp_path / "api.json"
    provider.write_text(json.dumps({"repository": "api", "provides": {"orders/http": "v1"}}))
    consumer = {
        "repository": "web",
        "requires": {"orders/http": "v2", "catalog/http": "v1"},
    }
    args = ["repo-contract-check", str(provider), "-", "--fail-on-change"]
    runner = CliRunner()
    result = runner.invoke(main, args, input=json.dumps(consumer))
    assert result.exit_code == 2, result.output
    assert {item["reason"] for item in json.loads(result.output)["findings"]} == {
        "missing_provider", "revision_mismatch",
    }
    consumer["requires"] = {"orders/http": "v1"}
    assert runner.invoke(main, args, input=json.dumps(consumer)).exit_code == 0


def test_secret_migration_tracks_unverified_consumers_and_rotation():
    secret = {"id": "db-password", "owner": "platform", "consumers": ["api", "worker"]}
    args = ["secret-migration-plan", "-", "--require-ready"]
    runner = CliRunner()

    def run():
        return runner.invoke(main, args, input=json.dumps({"secrets": [secret]}))

    result = run()
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["items"][0]["unverified_consumers"] == ["api", "worker"]
    secret.update(
        reference="vault:app/database", verified_consumers=["api", "worker"],
        rotation_verified=True, legacy_removed=True, plaintext_scan_clean=True,
    )
    assert run().exit_code == 0
    secret["value"] = "private-input"
    result = run()
    assert result.exit_code == 1
    assert "private-input" not in result.output


def test_dependency_review_rejects_unapproved_identity_registry_and_artifact(tmp_path):
    actual = {
        "purl": "pkg:pypi/example@1.0", "registry": "https://trusted.invalid/packages",
        "sha256": "0" * 64,
    }
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps({"dependencies": [actual]}))
    args = ["dependency-review", str(approved), "-", "--fail-on-unapproved"]
    runner = CliRunner()
    equivalent = {**actual, "registry": "https://TRUSTED.invalid:443/packages/"}
    result = runner.invoke(main, args, input=json.dumps({"dependencies": [equivalent]}))
    assert result.exit_code == 0, result.output
    changed = {**actual, "registry": "https://other.invalid/packages", "sha256": "1" * 64}
    unapproved = {**actual, "purl": "pkg:pypi/unknown@1.0"}
    result = runner.invoke(main, args, input=json.dumps({"dependencies": [changed, unapproved]}))
    assert result.exit_code == 2, result.output
    assert {item["reason"] for item in json.loads(result.output)["findings"]} == {
        "registry_mismatch", "digest_mismatch", "unapproved_package",
    }


def test_sbom_review_prefers_purl_and_reports_declared_dependency_path(tmp_path):
    spec = {
        "bomFormat": "CycloneDX",
        "metadata": {"component": {"name": "application", "bom-ref": "root"}},
        "components": [
            {"name": "lib", "version": "1", "bom-ref": "a", "purl": "pkg:pypi/lib@1"},
            {"name": "lib", "version": "1", "bom-ref": "b", "purl": "pkg:npm/lib@1"},
        ],
        "dependencies": [{"ref": "root", "dependsOn": ["a"]}, {"ref": "a", "dependsOn": ["b"]}],
    }
    artifact = {"name": "lib", "version": "1"}
    scan = {
        "matches": [
            {"vulnerability": {"id": "TEST-1"}, "artifact": {**artifact, "purl": "pkg:npm/lib@1"}},
            {"vulnerability": {"id": "TEST-2"}, "artifact": artifact},
            {"vulnerability": {"id": "TEST-3"}, "artifact": {**artifact, "purl": "pkg:gem/lib@1"}},
        ]
    }
    bom = tmp_path / "bom.json"
    bom.write_text(json.dumps(spec))
    result = CliRunner().invoke(main, ["sbom-review", str(bom), "-"], input=json.dumps(scan))
    assert result.exit_code == 0, result.output
    findings = json.loads(result.output)["findings"]
    assert findings[0]["match"] == "purl"
    assert findings[0]["dependency_depth"] == 2
    assert findings[1]["match"] == "ambiguous"
    assert findings[2]["match"] == "unmatched"
    runtime = tmp_path / "runtime.json"
    observations = {
        "bom_sha256": sha256(bom.read_bytes()).hexdigest(),
        "observations": [
            {"bom_ref": "b", "id": "TEST-1", "symbol": "private-symbol"},
            {"bom_ref": "b", "id": "TEST-2", "symbol": "ambiguous-symbol"},
        ],
    }
    runtime.write_text(json.dumps(observations))
    args = ["sbom-review", str(bom), "-", "--runtime", str(runtime)]
    result = CliRunner().invoke(main, args, input=json.dumps(scan))
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert "private-symbol" not in result.output
    assert [item["runtime_reachability"] for item in report["findings"]] == [
        "reported_observed", "unknown", "unknown",
    ]
    assert report["unmatched_runtime_pairs"] == 1
    observations["bom_sha256"] = "0" * 64
    runtime.write_text(json.dumps(observations))
    assert CliRunner().invoke(main, args, input=json.dumps(scan)).exit_code == 1


def test_gitops_bundle_checks_all_resources_before_apply():
    from radea.gitops import _bundle

    valid = b"apiVersion: v1\nkind: ConfigMap\nmetadata: {name: a, namespace: lab}\n"
    service = (
        b"apiVersion: v1\nkind: Service\nmetadata: {name: b, namespace: lab}\n"
        b"spec: {selector: {app: demo}, ports: [{port: 80}]}\n"
    )
    import pytest

    assert len(_bundle(valid + b"---\n" + service, "lab")) == 2
    with pytest.raises(ValueError, match="target namespace"):
        _bundle(valid + b"---\n" + service.replace(b"namespace: lab", b"namespace: other"), "lab")
    with pytest.raises(ValueError, match="ClusterIP"):
        _bundle(service.replace(b"spec: {", b"spec: {type: NodePort, "), "lab")


def test_metric_watch_emits_transitions_and_recovers_from_invalid_input(tmp_path, monkeypatch):
    import time

    series = tmp_path / "rolling.json"

    def sample(value):
        return json.dumps({"series": {"load": {"history": [1] * 5, "current": value}}})

    series.write_text(sample(9))
    revisions = iter([sample(9), "invalid", "invalid", sample(1)])

    def advance(_seconds):
        content = next(revisions, None)
        if content is None:
            raise KeyboardInterrupt
        series.write_text(content)

    monkeypatch.setattr(time, "sleep", advance)
    result = CliRunner().invoke(
        main, ["metric-anomalies", str(series), "--watch", "1", "--window", "5"]
    )
    assert [json.loads(line)["event"] for line in result.stdout.splitlines()] == [
        "opened",
        "recovered",
    ]
    assert result.stderr.count('"event": "input_error"') == 1
    assert result.stderr.count('"event": "input_recovered"') == 1


def test_rbac_access_scopes_rolebinding_and_matches_resource_name():
    policy = """\
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: view-demo}
rules:
  - apiGroups: [""]
    resources: ["*/status"]
    verbs: [get]
    resourceNames: [demo]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: read, namespace: lab}
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: ClusterRole, name: view-demo}
subjects:
  - {kind: ServiceAccount, name: reader}
"""
    runner = CliRunner()
    args = [
        "rbac-access",
        "-",
        "--user",
        "system:serviceaccount:lab:reader",
        "--verb",
        "get",
        "--resource",
        "pods/status",
        "--resource-name",
        "demo",
    ]
    result = runner.invoke(main, [*args, "--namespace", "lab"], input=policy)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["grants"][0]["binding"] == "read"
    assert json.loads(runner.invoke(main, args, input=policy).output)["decision"] == (
        "no_grant_in_snapshot"
    )
    assert (
        json.loads(
            runner.invoke(
                main,
                [*args, "--namespace", "lab"],
                input=policy.replace("name: view-demo}", "name: absent}", 1),
            ).output
        )["decision"]
        == "unknown"
    )


def test_ci_shadow_compares_observed_results_and_missing_tests(tmp_path):
    baseline = tmp_path / "before.xml"
    baseline.write_text(
        '<testsuite><testcase name="present"/><testcase name="removed"/></testsuite>'
    )
    candidate = (
        '<testsuite><testcase name="present"><failure>private error</failure>'
        "</testcase></testsuite>"
    )
    result = CliRunner().invoke(
        main, ["ci-shadow", str(baseline), "-", "--fail-on-change"], input=candidate
    )
    assert result.exit_code == 2, result.output
    assert "private error" not in result.output
    assert json.loads(result.output)["changes"] == [
        {"test": "present", "baseline": "pass", "candidate": "fail"},
        {"test": "removed", "baseline": "pass", "candidate": None},
    ]


def test_ci_shadow_compares_artifact_digests_and_rejects_different_commits(tmp_path):
    junit = tmp_path / "result.xml"
    junit.write_text('<testsuite><testcase name="ok"/></testsuite>')
    baseline, candidate = tmp_path / "old.json", tmp_path / "new.json"
    old = {"revision": "a" * 40, "duration_ms": 220, "artifacts": {"wheel": "0" * 64}}
    new = {"revision": "a" * 40, "duration_ms": 180, "artifacts": {"wheel": "1" * 64}}
    baseline.write_text(json.dumps(old))
    candidate.write_text(json.dumps(new))
    args = [
        "ci-shadow", str(junit), str(junit), "--baseline-build", str(baseline),
        "--candidate-build", str(candidate), "--fail-on-change",
    ]
    runner = CliRunner()
    result = runner.invoke(main, args)
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert report["changes"] == []
    assert report["build"]["duration_delta_ms"] == -40
    assert report["build"]["artifact_changes"] == [
        {"artifact": "wheel", "change": "digest_changed"},
    ]
    new["revision"] = "b" * 40
    candidate.write_text(json.dumps(new))
    result = runner.invoke(main, args)
    assert result.exit_code == 1
    assert "different Git revisions" in result.output


def test_cost_report_preserves_decimal_credit_and_separate_currencies():
    export = (
        "BillingCurrency,BilledCost,ServiceName,Tags\n"
        'USD,0.10,Compute,"{""team"":""api""}"\n'
        'USD,0.20,Compute,"{""team"":""api""}"\n'
        "USD,-0.05,Compute,\n"
        'EUR,0.80,Compute,"{""team"":""api""}"\n'
    )
    result = CliRunner().invoke(
        main, ["cost-report", "-", "--by", "ServiceName", "--tag", "team"], input=export
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["unattributed_rows"] == 1
    assert report["totals"] == {"EUR": "0.80", "USD": "0.25"}
    assert report["allocations"][-1]["billed_cost"] == "0.30"


def test_gitops_polling_resynchronizes_unchanged_revision(tmp_path, monkeypatch):
    import time

    from radea import gitops

    config = tmp_path / "kubeconfig"
    config.touch()
    attempts = []

    def sync(*args, **kwargs):
        attempts.append((args, kwargs))
        return {"commit": "same", "resources_applied": 2}

    def sleep(interval):
        assert interval == 2
        if len(attempts) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(gitops, "sync", sync)
    monkeypatch.setattr(time, "sleep", sleep)
    result = CliRunner().invoke(
        main,
        [
            "gitops-sync",
            "--repo",
            str(tmp_path),
            "--manifest",
            "bundle.yaml",
            "--kubeconfig",
            str(config),
            "--context",
            "lab",
            "--namespace",
            "lab",
            "--interval",
            "2",
        ],
    )
    assert len(attempts) == 2
    assert result.stdout.count('"resources_applied": 2') == 2


def test_canary_gate_distinguishes_hold_promote_and_rollback():
    runner = CliRunner()
    args = ["canary-gate", "-", "--max-p95-ms", "200", "--min-requests", "2"]
    healthy = {"ok": True, "latency_ms": 30}
    for requests, status, decision in (
        ([healthy], 3, "hold"),
        ([healthy, healthy], 0, "promote"),
        ([healthy, {"ok": False}], 2, "rollback"),
        ([healthy, {"ok": True, "latency_ms": 201}], 2, "rollback"),
    ):
        result = runner.invoke(main, args, input=json.dumps({"requests": requests}))
        assert result.exit_code == status, result.output
        assert json.loads(result.output)["decision"] == decision


def test_mutation_test_runs_pytest_and_leaves_original_module_unchanged(tmp_path):
    module = tmp_path / "boundary_demo.py"
    original = "def below(n):\n    return n < 5\n\ndef enabled():\n    return True\n"
    module.write_text(original)
    tests = tmp_path / "test_boundary_demo.py"
    tests.write_text(
        "from boundary_demo import below\n\n"
        "def test_boundary():\n    assert below(4)\n    assert not below(5)\n"
    )
    result = CliRunner().invoke(
        main, ["mutation-test", str(module), str(tests), "--fail-on-survival"]
    )
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert report["killed"] == 1
    assert report["survived"] == 1
    assert report["inconclusive"] == 0
    assert module.read_text() == original
def test_cost_report_compares_exact_currency_and_dimension_deltas(tmp_path):
    header = "BillingCurrency,BilledCost,ServiceName\n"
    baseline = tmp_path / "baseline.csv"
    baseline.write_text(header + "USD,1.01,compute\nUSD,0.01,old\nEUR,2.50,compute\n")
    current = header + "USD,1.02,compute\nEUR,2.50,compute\nUSD,0.03,new\n"
    result = CliRunner().invoke(main, [
        "cost-report", "-", "--baseline", str(baseline), "--by", "ServiceName",
    ], input=current)
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["current"]["totals"] == {"EUR": "2.50", "USD": "1.05"}
    assert report["changes"] == [
        {"currency": "USD", "dimensions": {"ServiceName": "compute"},
         "baseline": "1.01", "current": "1.02", "delta": "0.01"},
        {"currency": "USD", "dimensions": {"ServiceName": "new"},
         "baseline": None, "current": "0.03", "delta": "0.03"},
        {"currency": "USD", "dimensions": {"ServiceName": "old"},
         "baseline": "0.01", "current": None, "delta": "-0.01"},
    ]
