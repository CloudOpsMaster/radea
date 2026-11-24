import json
import subprocess
import sys

from click.testing import CliRunner

from radea.cli import main


def test_flag_experiment_deduplicates_cohorts_and_rejects_conflicts():
    control = {"cohort": "private-a", "variant": "control", "success": False}
    candidate = {"cohort": "private-b", "variant": "candidate", "success": True}
    data = {"experiment": "checkout", "observations": [control, control, candidate]}
    args = ["flag-experiment", "-", "--control", "control"]
    runner = CliRunner()
    result = runner.invoke(main, args, input=json.dumps(data))
    assert result.exit_code == 0, result.output
    assert "private-" not in result.output
    report = json.loads(result.output)
    assert report["duplicates"] == 1
    assert report["variants"][0] == {
        "name": "candidate", "cohorts": 1, "successes": 1, "success_rate": 1.0,
        "delta_percentage_points": 100.0,
    }
    data["observations"].append({**control, "variant": "candidate"})
    result = runner.invoke(main, args, input=json.dumps(data))
    assert result.exit_code == 1
    assert "Conflicting observation at position 4" in result.output


def test_code_review_advisory_and_explicit_gate():
    code = """
def demo(value, defaults=[]):
    try:
        return 10 is value
    except:
        pass
"""
    runner = CliRunner()
    args = ["code-review", "-", "--output", "json"]
    result = runner.invoke(main, args, input=code)
    assert result.exit_code == 0, result.output
    assert {item["rule"] for item in json.loads(result.output)["findings"]} == {
        "CODE001",
        "CODE002",
        "CODE003",
    }
    assert runner.invoke(main, [*args, "--fail-on", "medium"], input=code).exit_code == 2


def test_debug_patch_guards_pod_identity_and_appends_without_existing_payload():
    pod = {
        "apiVersion": "v1", "kind": "Pod",
        "metadata": {
            "name": "app", "namespace": "lab", "uid": "fixture-1", "resourceVersion": "42",
        },
        "spec": {"containers": [{"name": "app"}],
                 "ephemeralContainers": [{"name": "other", "args": ["private-argument"]}]},
    }
    image = "docker.io/library/busybox@sha256:" + "a" * 64
    args = ["k8s-debug-plan", "-", "--image", image]
    runner = CliRunner()
    result = runner.invoke(main, args, input=json.dumps(pod))
    assert result.exit_code == 0, result.output
    patch = json.loads(result.output)
    assert [operation["path"] for operation in patch] == [
        "/metadata/uid", "/metadata/resourceVersion", "/spec/ephemeralContainers/-",
    ]
    assert patch[2]["value"]["securityContext"]["runAsUser"] == 65534
    assert "private-argument" not in result.output
    pod["spec"]["hostPID"] = True
    assert runner.invoke(main, args, input=json.dumps(pod)).exit_code == 1


def test_code_review_baseline_filters_unchanged_findings(tmp_path):
    original = "def existing(items=[]):\n    return items\n"
    baseline = tmp_path / "before.py"
    baseline.write_text(original)
    candidate = "# moved old code down\n" + original + "\nsettings = {1: True, 1: False}\n"
    args = ["code-review", "-", "--baseline", str(baseline), "--output", "json",
            "--fail-on", "medium"]
    result = CliRunner().invoke(main, args, input=candidate)
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert [(item["rule"], item["line"]) for item in report["findings"]] == [("CODE004", 5)]


def test_code_review_flags_overwrites_and_return_during_cleanup():
    code = """\
def demo(key):
    distinct = {1: "one", "1": "text", key: "dynamic"}
    duplicate = {1: "one", True: "overwrite"}
    try:
        return distinct
    finally:
        return duplicate
"""
    result = CliRunner().invoke(main, ["code-review", "-", "--output", "json"], input=code)
    assert result.exit_code == 0, result.output
    assert {(item["rule"], item["line"]) for item in json.loads(result.output)["findings"]} == {
        ("CODE004", 3),
        ("CODE005", 7),
    }


def test_docs_answer_retrieves_cited_passages_and_abstains(tmp_path):
    runbook = tmp_path / "rollouts.md"
    runbook.write_text("Helm rollback uses a retained revision.\nCheck readiness afterward.\n")
    runner = CliRunner()
    result = runner.invoke(main, ["docs-answer", "Helm rollback", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "passages_found"
    (citation,) = payload["citations"]
    assert citation["path"] == str(runbook)
    assert (citation["start_line"], citation["end_line"]) == (1, 2)
    assert "retained revision" in citation["excerpt"]

    result = runner.invoke(main, ["docs-answer", "Kafka reassignment", str(tmp_path)])
    assert json.loads(result.output)["status"] == "no_documented_answer"


def test_scaffold_creates_runnable_service_and_refuses_existing_directory(tmp_path):
    destination = tmp_path / "sample"
    args = [
        "service-scaffold",
        str(destination),
        "--name",
        "sample",
        "--base-image",
        "docker.io/library/python@sha256:" + "a" * 64,
    ]
    runner = CliRunner()
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    smoke = subprocess.run(
        [sys.executable, "-B", "-m", "unittest", "-v"],
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert smoke.returncode == 0, smoke.stderr
    assert "Ran 2 tests" in smoke.stderr
    assert "COPY --chmod=0444 app.py ." in (destination / "Dockerfile").read_text()
    for command, target in (
        ("ci-review", destination / ".github/workflows/ci.yml"),
        ("dockerfile-review", destination / "Dockerfile"),
    ):
        review = runner.invoke(main, [command, str(target), "--fail-on", "low"])
        assert review.exit_code == 0, review.output
    app = (destination / "app.py").read_text()
    assert runner.invoke(main, args).exit_code == 1
    assert (destination / "app.py").read_text() == app


def test_service_scaffold_writes_catalog_descriptor_for_an_explicit_owner(tmp_path):
    import yaml

    destination = tmp_path / "service"
    args = [
        "service-scaffold", str(destination), "--name", "on", "--base-image",
        "docker.io/library/python@sha256:" + "a" * 64, "--owner", "platform",
    ]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    descriptor = yaml.safe_load((destination / "catalog-info.yaml").read_text())
    assert descriptor == {
        "apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "on"},
        "spec": {"type": "service", "lifecycle": "experimental", "owner": "platform"},
    }


def test_migration_route_prefers_specific_prefix_and_supports_rollback():
    plan = {
        "routes": [
            {"prefix": "/billing", "candidate_percent": 100},
            {"prefix": "/billing/legacy", "candidate_percent": 0},
        ]
    }
    runner = CliRunner()

    def route(path):
        result = runner.invoke(
            main,
            ["migration-route", "-", "--path", path, "--cohort", "example"],
            input=json.dumps(plan),
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)["backend"]

    assert route("/billing") == "candidate"
    assert route("/billing/legacy/report") == "legacy"
    assert route("/billing2") == "legacy"
    plan["routes"][0]["candidate_percent"] = 0
    assert route("/billing") == "legacy"


def test_helpdesk_tracks_only_opted_in_unanswered_categories(tmp_path):
    docs = tmp_path / "runbook.md"
    docs.write_text("Helm rollback restores a previous revision.\n")
    log = tmp_path / "gaps.jsonl"
    runner = CliRunner()
    options = ["--gap-log", str(log), "--topic", "deployment"]
    for query in ("Kafka broker rebalance", "Private training question", "Helm rollback"):
        result = runner.invoke(main, ["docs-answer", query, str(docs), *options])
        assert result.exit_code == 0, result.output
    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert entries == [{"topic": "deployment"}, {"topic": "deployment"}]
    result = runner.invoke(main, ["docs-backlog", str(log)])
    assert json.loads(result.output)["topics"] == [{"topic": "deployment", "requests": 2}]


def test_ci_timing_reports_feedback_and_overlap_without_inventing_samples():
    def job(start, end, outcome, cache="unknown"):
        return {
            "started_seconds": start,
            "finished_seconds": end,
            "outcome": outcome,
            "cache": cache,
        }

    payload = {
        "baseline": [
            {
                "duration_seconds": 20,
                "diagnosed_seconds": 25,
                "jobs": [job(0, 10, "fail", "miss"), job(3, 12, "pass")],
            }
        ],
        "candidate": [
            {"duration_seconds": 12, "jobs": [job(0, 4, "pass", "hit"), job(4, 10, "pass")]}
        ],
    }
    result = CliRunner().invoke(main, ["ci-timing", "-"], input=json.dumps(payload))
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["delta"]["wall_median_seconds"] == -8
    assert data["delta"]["first_failure_median_seconds"] is None
    assert data["baseline"]["first_failure_median_seconds"] == 10
    assert data["baseline"]["diagnosis_median_seconds"] == 25
    assert data["baseline"]["peak_parallel_jobs_median"] == 2
    assert data["candidate"]["peak_parallel_jobs_median"] == 1
    assert data["candidate"]["observed_cache_hit_rate"] == 1


def test_signed_image_checks_actual_bytes_and_signer(tmp_path):
    import base64
    import hashlib
    import shutil

    import pytest

    if shutil.which("openssl") is None:
        pytest.skip("OpenSSL is required for the signature integration test")
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(
        b'{"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json"}'
    )
    repository = "docker.io/example/service"
    payload = tmp_path / "payload.json"
    payload.write_text(
        json.dumps(
            {
                "critical": {
                    "type": "cosign container image signature",
                    "identity": {"docker-reference": repository},
                    "image": {
                        "docker-manifest-digest": "sha256:"
                        + hashlib.sha256(manifest.read_bytes()).hexdigest()
                    },
                },
                "optional": None,
            }
        )
    )
    private = tmp_path / "private.pem"
    public = tmp_path / "public.pem"
    signature = tmp_path / "signature.b64"

    def openssl(*arguments):
        return subprocess.run(
            ["openssl", *map(str, arguments)], check=True, capture_output=True, timeout=10
        ).stdout

    openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", private)
    openssl("pkey", "-in", private, "-pubout", "-out", public)
    signature.write_bytes(base64.b64encode(openssl("dgst", "-sha256", "-sign", private, payload)))
    args = [
        "image-verify",
        str(manifest),
        str(payload),
        str(signature),
        "--key",
        str(public),
        "--repository",
        repository,
    ]
    runner = CliRunner()
    good = runner.invoke(main, args)
    assert good.exit_code == 0, good.output
    bad_repository = runner.invoke(main, [*args[:-1], "docker.io/example/other"])
    assert json.loads(bad_repository.output)["reason"] == "repository_mismatch"
    manifest.write_bytes(manifest.read_bytes() + b" ")
    modified = runner.invoke(main, args)
    assert modified.exit_code == 2
    assert json.loads(modified.output)["reason"] == "digest_mismatch"
    payload.write_text(payload.read_text() + "\n")
    invalid = runner.invoke(main, args)
    assert json.loads(invalid.output)["reason"] == "signature_verification_failed"


def test_helm_matrix_reports_only_affected_environment(tmp_path):
    import shutil

    import pytest

    if shutil.which("helm") is None:
        pytest.skip("Helm is required for the render integration test")
    old, new = (tmp_path / name for name in ("before", "after"))
    for chart in (old, new):
        (chart / "templates").mkdir(parents=True)
        (chart / "Chart.yaml").write_text("apiVersion: v2\nname: sample\nversion: 1.0.0\n")
        (chart / "values.yaml").write_text("message: default\n")
    header = "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: settings}\ndata:\n"
    (old / "templates/settings.yaml").write_text(
        header + "  value: {{ .Values.message | quote }}\n"
    )
    (new / "templates/settings.yaml").write_text(
        header + '  value: {{ if eq .Values.message "production" }}"changed"'
        "{{ else }}{{ .Values.message | quote }}{{ end }}\n"
    )
    staging = tmp_path / "stage.yaml"
    prod = tmp_path / "prod.yaml"
    staging.write_text("message: stage\n")
    prod.write_text("message: production\n")
    result = CliRunner().invoke(
        main,
        [
            "helm-matrix",
            str(old),
            str(new),
            "--values",
            f"stage={staging}",
            "--values",
            f"prod={staging}",
            "--values",
            f"prod={prod}",
            "--fail-on-change",
        ],
    )
    assert result.exit_code == 2, result.output
    cases = {
        item["environment"]: item["changes"] for item in json.loads(result.output)["environments"]
    }
    assert cases["stage"] == []
    assert cases["prod"][0]["fields"] == ["data"]
    assert "production" not in result.output


def test_helm_matrix_validates_values_key_refactor_with_real_helm(tmp_path):
    import shutil

    import pytest

    if shutil.which("helm") is None:
        pytest.skip("Helm is required for the render integration test")
    old, new = (tmp_path / name for name in ("before", "after"))
    for chart, key in [(old, "message"), (new, "response")]:
        (chart / "templates").mkdir(parents=True)
        (chart / "Chart.yaml").write_text("apiVersion: v2\nname: sample\nversion: 1.0.0\n")
        (chart / "values.yaml").write_text(f"{key}: default\n")
        (chart / "values.schema.json").write_text(json.dumps({
            "type": "object", "properties": {key: {"type": "string"}},
            "required": [key], "additionalProperties": False,
        }))
    header = "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: settings}\ndata:\n"
    (old / "templates/settings.yaml").write_text(header + "  text: {{ .Values.message | quote }}\n")
    (new / "templates/settings.yaml").write_text(header + '  text: {{ include "sample.text" . }}\n')
    (new / "templates/_helpers.tpl").write_text(
        '{{ define "sample.text" }}{{ .Values.response | quote }}{{ end }}\n'
    )
    baseline, candidate = tmp_path / "legacy.yaml", tmp_path / "refactored.yaml"
    baseline.write_text("message: production\n")
    candidate.write_text("response: production\n")
    args = [
        "helm-matrix", str(old), str(new), "--before-values", f"prod={baseline}",
        "--after-values", f"prod={candidate}", "--fail-on-change",
    ]
    runner = CliRunner()
    result = runner.invoke(main, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["environments"] == [{"environment": "prod", "changes": []}]
    candidate.write_text("response: drift\n")
    assert runner.invoke(main, args).exit_code == 2
    candidate.write_text("message: production\n")
    assert runner.invoke(main, args).exit_code == 1


def test_cutover_simulation_reverts_only_applied_steps_in_reverse():
    fields = {
        "owner": "ops",
        "apply": "switch",
        "verify": "check",
        "rollback": "restore",
        "verify_rollback": "check restored state",
    }
    data = {
        "name": "Cutover",
        "steps": [{"id": step, **fields} for step in ("first", "failure", "after")],
    }
    result = CliRunner().invoke(
        main, ["cutover-plan", "-", "--fail-at", "failure"], input=json.dumps(data)
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["draft"]
    events = report["simulation"]["events"]
    assert [event["step"] for event in events if event["phase"] == "rollback"] == [
        "failure",
        "first",
    ]
    assert all(event["step"] != "after" for event in events)


def test_shell_review_compares_diagnostics_without_line_number_noise(tmp_path):
    import shutil

    import pytest

    if shutil.which("shellcheck") is None:
        pytest.skip("ShellCheck is required for the shell review integration test")
    baseline = tmp_path / "old.sh"
    baseline.write_text('#!/bin/bash\nname=$1\nprintf "%s\\n" $name\n')
    candidate = '#!/bin/bash\n\nname=$1\nprintf "%s\\n" $name\ncd /tmp\n'
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["shell-review", "-", "--baseline", str(baseline), "--fail-on-new"],
        input=candidate,
    )
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert {item["code"] for item in report["introduced"]} == {2164}
    assert any(item["code"] == 2086 for item in report["diagnostics"])


def test_k8s_capture_scopes_reads_and_omits_event_messages(tmp_path, monkeypatch):
    from radea import kube_capture

    config = tmp_path / "kubeconfig"
    config.touch()
    calls = []

    def respond(base, arguments, limit):
        calls.append(arguments)
        assert base[base.index("--context") + 1] == "lab"
        assert base[base.index("--namespace") + 1] == "space"
        assert limit > 0
        if arguments[:2] == ["get", "pod"]:
            return b'{"kind":"Pod","metadata":{"name":"demo","namespace":"space","uid":"uid-1"}}'
        if arguments[:2] == ["get", "events"]:
            assert "involvedObject.uid=uid-1" in arguments
            return json.dumps(
                {
                    "items": [
                        {
                            "involvedObject": {"uid": "uid-1"},
                            "reason": "Started",
                            "message": "private",
                        },
                        {"involvedObject": {"uid": "other"}, "reason": "WrongPod"},
                    ]
                }
            ).encode()
        assert arguments[:2] == ["logs", "demo"] and "--previous" in arguments
        return b"password=hunter2-secret-demo"

    monkeypatch.setattr(kube_capture, "_get", respond)
    result = CliRunner().invoke(
        main,
        [
            "k8s-capture",
            "demo",
            "--kubeconfig",
            str(config),
            "--context",
            "lab",
            "--namespace",
            "space",
            "--container",
            "app",
            "--previous",
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert [item["reason"] for item in report["events"]] == ["Started"]
    assert len(calls) == 4
    assert "hunter2-secret-demo" not in result.output
    assert "private" not in result.output


def test_feature_flag_respects_group_override_and_stable_variants():
    policy = {
        "flags": {
            "checkout": {
                "enabled": True,
                "rollout": 100,
                "groups": ["beta"],
                "variants": {"treatment": 60, "control": 40},
            }
        }
    }
    runner = CliRunner()
    args = ["flag-evaluate", "-", "checkout", "--cohort", "caller-demo"]
    blocked = runner.invoke(main, args, input=json.dumps(policy))
    assert json.loads(blocked.output)["reason"] == "group_mismatch"
    eligible = [*args, "--group", "beta"]
    first = runner.invoke(main, eligible, input=json.dumps(policy))
    second = runner.invoke(main, eligible, input=json.dumps(policy, sort_keys=True))
    assert first.exit_code == second.exit_code == 0, first.output
    assert first.output == second.output
    assert json.loads(first.output)["variant"] in ("control", "treatment")
    assert "caller-demo" not in first.output
    policy["flags"]["checkout"]["enabled"] = False
    disabled = runner.invoke(main, eligible, input=json.dumps(policy))
    assert json.loads(disabled.output)["variant"] is None


def test_workload_plan_distinguishes_controllers_and_conflicts():
    runner = CliRunner()
    for options, kind in (
        ([], "Deployment"),
        (["--per-node"], "DaemonSet"),
        (["--per-pod-storage"], "StatefulSet"),
        (["--scheduled"], "CronJob"),
    ):
        result = runner.invoke(main, ["k8s-workload-plan", *options])
        assert json.loads(result.output)["kind"] == kind
    conflict = runner.invoke(main, ["k8s-workload-plan", "--per-node", "--ordered"])
    assert conflict.exit_code == 1


def test_postmortem_review_checks_digest_and_human_evidence(tmp_path):
    import hashlib

    source = tmp_path / "draft.json"
    source.write_text(
        json.dumps(
            {
                "command": "triage",
                "draft": True,
                "evidence": {"s1:L2": "observed timeout"},
            }
        )
    )
    decisions = {
        "draft_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "reviewer": "oncall",
        "conclusion": "Confirmed by operator",
        "cause_status": "confirmed_by_reviewer",
        "evidence_ids": ["s1:L2"],
        "action_items": [{"owner": "team", "action": "Review timeout", "due": "2026-12-01"}],
    }
    args = ["postmortem-review", str(source), "-"]
    runner = CliRunner()
    result = runner.invoke(main, args, input=json.dumps(decisions))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["action_items"][0]["owner"] == "team"
    decisions["evidence_ids"] = ["unknown"]
    assert runner.invoke(main, args, input=json.dumps(decisions)).exit_code == 1
    source.write_text(source.read_text() + "\n")
    changed = runner.invoke(main, args, input=json.dumps(decisions))
    assert changed.exit_code == 1 and "SHA-256" in changed.output


def test_test_scaffold_runs_generated_assertions_against_real_pytest(tmp_path):
    payload = {"cases": [{"id": "basic", "args": [2], "kwargs": {"scale": 3}, "expected": 6}]}
    result = CliRunner().invoke(
        main,
        ["test-scaffold", "-", "--module", "product_demo", "--function", "multiply"],
        input=json.dumps(payload),
    )
    assert result.exit_code == 0, result.output
    (tmp_path / "product_demo.py").write_text(
        "def multiply(number, scale): return number * scale\n"
    )
    (tmp_path / "test_generated.py").write_text(result.output)
    result_run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "test_generated.py"],
        cwd=tmp_path,
        timeout=10,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_run.returncode == 0, result_run.stdout + result_run.stderr


def test_prompt_prepare_selects_version_and_keeps_untrusted_context_separate(tmp_path):
    path = tmp_path / "library.json"
    path.write_text(
        json.dumps(
            {
                "templates": [
                    {"id": "incident", "version": "1", "instruction": "first", "inputs": ["log"]},
                    {
                        "id": "incident",
                        "version": "2",
                        "instruction": "Summarize facts",
                        "inputs": ["log"],
                    },
                ]
            }
        )
    )
    args = ["prompt-prepare", str(path), "-", "--template", "incident", "--version", "2"]
    runner = CliRunner()
    result = runner.invoke(main, args, input=json.dumps({"log": "password=demo-private-secret"}))
    assert result.exit_code == 0, result.output
    packet = json.loads(result.output)
    assert packet["instruction"] == "Summarize facts"
    assert packet["template"]["version"] == "2"
    assert "demo-private-secret" not in result.output
    assert runner.invoke(main, args, input="{}").exit_code == 1


def test_gitops_fetches_committed_bundle_and_rejects_bad_ref_before_apply(tmp_path, monkeypatch):
    from radea import gitops

    origin, working = tmp_path / "origin", tmp_path / "mirror"
    origin.mkdir()
    working.mkdir()

    def git(repo, *arguments):
        subprocess.run(
            ["git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *arguments],
            check=True,
            timeout=10,
            capture_output=True,
        )

    git(origin, "init", "--initial-branch=main")
    git(working, "init")
    git(working, "remote", "add", "source", str(origin))
    bundle = origin / "objects.yaml"

    def commit(value):
        bundle.write_text(
            "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: state, namespace: demo}\n"
            f"data: {{value: {value}}}\n"
        )
        git(origin, "add", "objects.yaml")
        git(
            origin,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--no-gpg-sign",
            "-m",
            "update",
        )

    calls = []
    real_run = gitops._run

    def execute(args, *, payload=None, env=None):
        if args[0] == "git":
            return real_run(args, payload=payload, env=env)
        calls.append((args, json.loads(payload), env))
        return b""

    monkeypatch.setattr(gitops, "_run", execute)
    args = (str(working), "refs/heads/main", "objects.yaml", "config", "lab", "demo", 65536)
    commit("first")
    first = gitops.sync(*args, remote="source", applyset="inventory")
    commit("second")
    second = gitops.sync(*args, remote="source", applyset="inventory")
    assert first["commit"] != second["commit"]
    assert calls[1][1]["items"][0]["data"]["value"] == "second"
    assert "--applyset=configmaps/inventory" in calls[1][0]
    assert calls[1][2]["KUBECTL_APPLYSET"] == "true"
    import pytest

    with pytest.raises(ValueError, match="refs/heads"):
        gitops.sync(args[0], "HEAD", *args[2:], remote="source")
    assert len(calls) == 2


def test_mutation_suite_uses_shared_tests_and_package_imports(tmp_path):
    package = tmp_path / "src" / "mutation_demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("from .checks import below\n")
    checks = package / "checks.py"
    contents = "def below(value):\n    return value < 5\n"
    checks.write_text(contents)
    (package / "flag.py").write_text("def flag():\n    return True\n")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_checks.py").write_text(
        "from mutation_demo import below\n\n"
        "def test_boundary():\n    assert below(4)\n    assert not below(5)\n"
    )
    result = CliRunner().invoke(
        main,
        [
            "mutation-suite",
            str(tmp_path),
            "--package",
            "src/mutation_demo",
            "--tests",
            "tests",
            "--fail-on-survival",
        ],
    )
    assert result.exit_code == 2, result.output
    report = json.loads(result.output)
    assert report["killed"] == report["survived"] == 1
    assert len({entry["module"] for entry in report["mutants"]}) == 2
    assert checks.read_text() == contents


def test_telemetry_capture_http_round_trip_projects_and_correlates(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from http.client import HTTPConnection

    from radea.incident_triage.otlp_capture import CaptureServer

    trace = "1a" * 16
    payloads = {
        "traces": {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": trace,
                                    "spanId": "1b" * 8,
                                    "name": "secret-span-name",
                                    "startTimeUnixNano": "10",
                                    "endTimeUnixNano": "20",
                                }
                            ]
                        }
                    ]
                }
            ]
        },
        "logs": {
            "resourceLogs": [
                {
                    "scopeLogs": [
                        {
                            "logRecords": [
                                {
                                    "traceId": trace,
                                    "severityNumber": 17,
                                    "body": {"stringValue": "secret-log-body"},
                                }
                            ]
                        }
                    ]
                }
            ]
        },
        "metrics": {
            "resourceMetrics": [
                {
                    "scopeMetrics": [
                        {
                            "metrics": [
                                {
                                    "name": "secret-metric-name",
                                    "gauge": {"dataPoints": [{"exemplars": [{"traceId": trace}]}]},
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    }
    with CaptureServer(tmp_path, 0, 65536) as server, ThreadPoolExecutor(1) as executor:
        thread = executor.submit(server.serve_forever)
        try:
            for signal, payload in payloads.items():
                connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                try:
                    connection.request(
                        "POST",
                        f"/v1/{signal}",
                        json.dumps(payload),
                        {"Content-Type": "application/json"},
                    )
                    response = connection.getresponse()
                    assert response.status == 200, response.read()
                    assert response.read() == b"{}"
                finally:
                    connection.close()
                assert "secret" not in (tmp_path / f"{signal}.jsonl").read_text()
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request(
                    "POST", "/v1/logs", b"x", {"Content-Type": "application/x-protobuf"}
                )
                assert connection.getresponse().status == 415
            finally:
                connection.close()
        finally:
            server.shutdown()
            thread.result(timeout=5)
    result = CliRunner().invoke(
        main,
        [
            "telemetry-review",
            str(tmp_path / "traces.jsonl"),
            "--logs",
            str(tmp_path / "logs.jsonl"),
            "--metrics",
            str(tmp_path / "metrics.jsonl"),
        ],
    )
    assert result.exit_code == 0, result.output
    (entry,) = json.loads(result.output)["traces"]
    assert (entry["span_count"], entry["error_logs"], entry["metric_exemplars"]) == (1, 1, 1)


def test_telemetry_capture_storage_quota_retains_completed_batches(tmp_path):
    from radea.incident_triage.otlp_capture import CaptureServer

    with CaptureServer(tmp_path, 0, 20) as server:
        assert server.append("logs", {"first": 1})
        assert not server.append("logs", {"second": 2})
    assert (tmp_path / "logs.jsonl").read_text() == '{"first":1}\n'


def test_preview_down_requires_exact_owner_and_api_preconditions(monkeypatch):
    from radea import preview

    name, labels = preview.identity("team", 41)
    metadata = {
        "name": name,
        "labels": {**labels, "radea.dev/preview-pr": "42"},
        "uid": "owned-uid",
        "resourceVersion": "7",
    }
    calls = []

    def run(base, *arguments, payload=None):
        calls.append((base, arguments, payload))
        if arguments[0] == "get":
            return json.dumps({"metadata": metadata}).encode()
        return b"{}"

    monkeypatch.setattr(preview, "_kubectl", run)
    import pytest

    with pytest.raises(ValueError, match="outside"):
        preview.down("team", 41, "config", "lab")
    assert len(calls) == 1
    metadata["labels"] = labels
    assert preview.down("team", 41, "config", "lab")["status"] == "deletion_requested"
    _, arguments, payload = calls[-1]
    assert arguments == ("delete", "--raw", f"/api/v1/namespaces/{name}", "-f", "-")
    assert payload["preconditions"] == {"uid": "owned-uid", "resourceVersion": "7"}


def test_preview_up_applies_only_to_selected_namespace(tmp_path, monkeypatch):
    from radea import preview

    config = tmp_path / "kubeconfig"
    config.touch()
    calls = []

    def run(base, *arguments, payload=None):
        calls.append((base, arguments, payload))
        return b""

    monkeypatch.setattr(preview, "_kubectl", run)
    result = CliRunner().invoke(
        main,
        [
            "preview-env",
            "--project",
            "team",
            "--pr",
            "42",
            "--kubeconfig",
            str(config),
            "--context",
            "isolated",
            "up",
            "--image",
            "registry.example.com/team/app:1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["namespace"] == "radea-team-pr-42"
    assert [call[1][0] for call in calls] == ["get", "create", "apply", "rollout"]
    items = calls[2][2]["items"]
    assert {item["kind"] for item in items} == {"Deployment", "Service"}
    assert all(item["metadata"]["namespace"] == "radea-team-pr-42" for item in items)
    assert items[0]["spec"]["template"]["spec"]["automountServiceAccountToken"] is False


def test_preview_pr_dispatches_same_repository_events_and_ignores_forks(tmp_path, monkeypatch):
    from radea import preview

    repository = "team/app"
    event_path = tmp_path / "event.json"
    config = tmp_path / "kubeconfig"
    config.touch()
    data = {
        "action": "opened",
        "number": 7,
        "repository": {"full_name": repository},
        "pull_request": {
            "number": 7,
            "state": "open",
            "base": {"repo": {"full_name": repository}},
            "head": {"repo": {"full_name": repository}},
        },
    }
    calls = []

    def up(*args):
        calls.append(("up", args))
        return {"status": "ready"}

    def down(*args):
        calls.append(("down", args))
        return {"status": "deletion_requested"}

    monkeypatch.setattr(preview, "up", up)
    monkeypatch.setattr(preview, "down", down)
    runner = CliRunner()
    arguments = [
        "preview-pr",
        str(event_path),
        "--repository",
        repository,
        "--project",
        "demo",
        "--kubeconfig",
        str(config),
        "--context",
        "isolated",
    ]
    event_path.write_text(json.dumps(data))
    raised = runner.invoke(main, arguments)
    assert raised.exit_code == 1 and not calls
    result = runner.invoke(main, [*arguments, "--image", "registry.example/team/app:1"])
    assert json.loads(result.output)["status"] == "ready"
    data["action"] = "closed"
    data["pull_request"]["state"] = "closed"
    event_path.write_text(json.dumps(data))
    result = runner.invoke(main, arguments)
    assert json.loads(result.output)["status"] == "deletion_requested"
    data["pull_request"]["head"]["repo"]["full_name"] = "fork/app"
    event_path.write_text(json.dumps(data))
    assert json.loads(runner.invoke(main, arguments).output)["status"] == "ignored"
    assert [kind for kind, _ in calls] == ["up", "down"]


def test_preview_sweep_filters_namespace_identity_and_rejects_bulk_delete(monkeypatch):
    from radea import preview

    def record(project, pr, date="2026-01-01T00:00:00Z"):
        name, labels = preview.identity(project, pr)
        return {
            "metadata": {
                "name": name,
                "labels": labels,
                "uid": f"uid-{pr}",
                "resourceVersion": "42",
                "creationTimestamp": date,
            }
        }

    unrelated = record("demo", 3)
    unrelated["metadata"]["name"] = "unrelated"
    items = [
        record("demo", 4),
        record("other", 1),
        unrelated,
        record("demo", 2, "2099-01-01T00:00:00Z"),
    ]
    calls = []

    def run(target, *args, payload=None):
        calls.append((target, args, payload))
        return json.dumps({"items": items}).encode() if args[0] == "get" else b"{}"

    monkeypatch.setattr(preview, "_kubectl", run)
    planned = preview.sweep("demo", "config", "lab", 60, False, 1)
    assert planned["candidates"] == ["radea-demo-pr-4"]
    assert len(calls) == 1
    items.append(record("demo", 5))
    import pytest

    with pytest.raises(ValueError, match="deletion limit"):
        preview.sweep("demo", "config", "lab", 60, True, 1)
    assert [call[1][0] for call in calls] == ["get", "get"]
    applied = preview.sweep("demo", "config", "lab", 60, True, 2)
    assert applied["deletion_requested"] == ["radea-demo-pr-4", "radea-demo-pr-5"]
    assert calls[-1][2]["preconditions"] == {"uid": "uid-5", "resourceVersion": "42"}


def test_migration_facade_routes_two_real_upstreams_and_applies_live_rollback(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from http.client import HTTPConnection
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from radea.migration import cohort_bucket
    from radea.migration_facade import Facade

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            assert "Authorization" not in self.headers and "Cookie" not in self.headers
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Set-Cookie", "private=value")
            self.end_headers()
            self.wfile.write(self.server.label)

        def log_message(self, _format, *_args):
            pass

    plan = tmp_path / "plan.json"
    plan.write_text('{"routes":[{"prefix":"/billing","candidate_percent":25}]}')
    with (
        HTTPServer(("127.0.0.1", 0), Backend) as legacy,
        HTTPServer(("127.0.0.1", 0), Backend) as candidate,
        Facade(str(plan), 0, legacy.server_port, candidate.server_port, 65536) as facade,
        ThreadPoolExecutor(3) as pool,
    ):
        legacy.label = b"legacy"
        candidate.label = b"candidate"
        active = [legacy, candidate, facade]
        threads = [pool.submit(server.serve_forever) for server in active]

        def request(path, cohort=None):
            connection = HTTPConnection("127.0.0.1", facade.server_port, timeout=5)
            try:
                headers = {"Authorization": "test-token", "Cookie": "session=example"}
                if cohort is not None:
                    headers["X-RADEA-Cohort"] = cohort
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                assert response.getheader("Set-Cookie") is None
                assert response.getheader("Cache-Control") == "no-store"
                return response.status, response.read()
            finally:
                connection.close()

        try:
            buckets = {}
            for index in range(3000):
                cohort = f"cohort-{index}"
                buckets.setdefault(cohort_bucket("/billing", cohort), cohort)
                if len(buckets) == 100:
                    break
            assert len(buckets) == 100
            results = [request("/billing/invoice", cohort) for cohort in buckets.values()]
            assert results.count((200, b"candidate")) == 25
            assert results.count((200, b"legacy")) == 75
            assert request("/billing") == (200, b"legacy")
            assert request("/billing?query=1", buckets[0])[0] == 400
            assert request("/billing", buckets[0]) == (200, b"candidate")
            changed = tmp_path / "next.json"
            changed.write_text('{"routes":[{"prefix":"/billing","candidate_percent":0}]}')
            changed.replace(plan)
            assert request("/billing", buckets[0]) == (200, b"legacy")
            plan.write_text("malformed")
            assert request("/billing", buckets[0])[0] == 503
            plan.write_text('{"routes":[{"prefix":"/billing","candidate_percent":100}]}')
            candidate.shutdown()
            candidate.server_close()
            assert request("/billing", buckets[0])[0] == 502
            assert request("/billing") == (200, b"legacy")
        finally:
            for server in reversed(active):
                server.shutdown()
            for thread in threads:
                thread.result(timeout=5)
