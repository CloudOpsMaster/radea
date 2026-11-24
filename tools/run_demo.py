"""Run the documented offline demo and preserve its JSON evidence."""

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKS = ("debug", "iac-review", "triage", "delivery", "platform")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=("full", *TRACKS), default="full")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--output-dir must be new or empty")
    inputs, reports = output / "inputs", output / "reports"
    inputs.mkdir(parents=True)
    reports.mkdir()
    env = {**os.environ, "RADEA_MODEL": "offline", "RADEA_AUDIT_DIR": str(output / "audit")}
    rows = []

    def fixture(name, data):
        path = inputs / name
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return str(path)

    def run(name, *argv, code=0, expect=lambda _: True):
        process = subprocess.run(
            [sys.executable, "-c", "from radea.cli import main; main()", *argv],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        try:
            report = json.loads(process.stdout)
        except ValueError:
            report = None
        filename = f"{name}.json"
        if report is not None:
            (reports / filename).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        ok = process.returncode == code and report is not None and expect(report)
        rows.append((filename, process.returncode, code, ok, shlex.join(["radea", *argv])))
        print(f"{'PASS' if ok else 'FAIL'}  {name} (exit {process.returncode}, expected {code})")
        if not ok:
            print(process.stderr[-2000:], file=sys.stderr)
            raise ValueError(f"Unexpected report or exit from {name}")
        return report

    enabled = TRACKS if args.track == "full" else (args.track,)
    try:
        if "debug" in enabled:
            run(
                "01-build-draft",
                "debug",
                "--log",
                "examples/logs/failed-build.log",
                "--output",
                "json",
                expect=lambda r: (
                    r["draft"]
                    and r["evidence_verified"]
                    and not r["verified"]
                    and r["category"] == "dependency_drift"
                ),
            )
            run(
                "02-ci-log-signals",
                "ci-observe",
                "examples/logs/failed-build.log",
                "--threshold",
                "1",
                expect=lambda r: any(c["anomaly"] for c in r["categories"]),
            )
            run(
                "03-ci-graph",
                "ci-graph",
                "examples/ci/github-good.yml",
                expect=lambda r: r["platform"] == "github" and bool(r["jobs"]),
            )

        if "iac-review" in enabled:
            destructive = "examples/evaluation/delete-plan.json"
            run(
                "04-terraform-draft",
                "iac-review",
                "--plan",
                destructive,
                "--output",
                "json",
                expect=lambda r: r["draft"] and not r["verified"],
            )
            run(
                "05-terraform-deny",
                "policy-check",
                "--plan",
                destructive,
                code=2,
                expect=lambda r: r["decision"] == "deny" and bool(r["destructive_actions"]),
            )
            safe = fixture(
                "safe-plan.json",
                {
                    "format_version": "1.2",
                    "resource_changes": [
                        {
                            "address": "terraform_data.example",
                            "change": {"actions": ["no-op"], "after": {"input": "stable"}},
                        }
                    ],
                },
            )
            run(
                "06-terraform-allow",
                "policy-check",
                "--plan",
                safe,
                expect=lambda r: r["decision"] == "allow",
            )
            run(
                "07-terraform-parity",
                "tf-plan-diff",
                safe,
                safe,
                "--fail-on-change",
                expect=lambda r: not r["changes"] and not r["incomplete"],
            )

        if "triage" in enabled:
            run(
                "08-incident-draft",
                "triage",
                "--logs",
                "examples/logs/incident.log",
                "--metrics",
                "examples/evaluation/metrics.json",
                "--output",
                "json",
                expect=lambda r: r["draft"] and r["evidence_verified"] and not r["verified"],
            )
            signal = fixture(
                "metrics.json",
                {
                    "series": {
                        "latency_p95": {"history": [100] * 10, "current": 150},
                    }
                },
            )
            run(
                "09-metric-anomaly",
                "metric-anomalies",
                signal,
                "--fail-on-anomaly",
                code=2,
                expect=lambda r: r["metrics"][0]["anomaly"],
            )
            draft = reports / "08-incident-draft.json"
            review = fixture(
                "incident-review.json",
                {
                    "draft_sha256": hashlib.sha256(draft.read_bytes()).hexdigest(),
                    "reviewer": "demo-operator",
                    "conclusion": "Verify the dependency before assigning a cause to the timeouts.",
                    "cause_status": "unknown",
                    "evidence_ids": [],
                    "action_items": [
                        {
                            "owner": "platform",
                            "action": "Correlate dependency latency",
                            "due": "2030-01-01",
                        }
                    ],
                },
            )
            run(
                "23-incident-handoff",
                "postmortem-review",
                str(draft),
                review,
                expect=lambda r: (
                    r["status"] == "human_review_recorded" and r["cause_status"] == "unknown"
                ),
            )
            trace = "a" * 32
            traces = fixture(
                "traces.json",
                {
                    "resourceSpans": [
                        {
                            "scopeSpans": [
                                {
                                    "spans": [
                                        {
                                            "traceId": trace,
                                            "spanId": "b" * 16,
                                            "startTimeUnixNano": "1000",
                                            "endTimeUnixNano": "2000",
                                            "status": {"code": 2},
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
            )
            logs = fixture(
                "otel-logs.json",
                {
                    "resourceLogs": [
                        {
                            "scopeLogs": [
                                {
                                    "logRecords": [
                                        {
                                            "traceId": trace,
                                            "severityNumber": 17,
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
            )
            metrics = fixture(
                "otel-metrics.json",
                {
                    "resourceMetrics": [
                        {
                            "scopeMetrics": [
                                {
                                    "metrics": [
                                        {
                                            "gauge": {
                                                "dataPoints": [
                                                    {"exemplars": [{"traceId": trace}]},
                                                ]
                                            }
                                        }
                                    ]
                                }
                            ],
                        }
                    ]
                },
            )
            run(
                "24-telemetry-correlation",
                "telemetry-review",
                traces,
                "--logs",
                logs,
                "--metrics",
                metrics,
                expect=lambda r: (
                    r["traces"][0]["error_logs"] == 1 and r["traces"][0]["metric_exemplars"] == 1
                ),
            )

        if "delivery" in enabled:
            for name, command, source in (
                ("10-kubernetes", "k8s-review", "examples/k8s/bad.yaml"),
                ("11-dockerfile", "dockerfile-review", "examples/docker/Dockerfile.bad"),
                ("12-ci-security", "ci-review", "examples/ci/github-bad.yml"),
                ("13-terraform-static", "tf-review", "examples/terraform/insecure.tf"),
                ("14-test-quality", "test-review", "examples/tests/bad.py"),
            ):
                run(
                    name,
                    command,
                    source,
                    "--output",
                    "json",
                    "--fail-on",
                    "low",
                    code=2,
                    expect=lambda r: bool(r["findings"]),
                )
            run(
                "15-kubernetes-good",
                "k8s-review",
                "examples/k8s/good.yaml",
                "--output",
                "json",
                "--fail-on",
                "high",
                expect=lambda r: not any(f["severity"] == "high" for f in r["findings"]),
            )
            for name, samples, decision, exit_code in (
                ("16-canary-promote", [{"ok": True, "latency_ms": 42}] * 5, "promote", 0),
                ("17-canary-hold", [{"ok": True, "latency_ms": 42}], "hold", 3),
                ("18-canary-rollback", [{"ok": False}] * 5, "rollback", 2),
            ):
                measurements = fixture(f"{name}.json", {"requests": samples})
                run(
                    name,
                    "canary-gate",
                    measurements,
                    "--min-requests",
                    "5",
                    "--max-p95-ms",
                    "100",
                    code=exit_code,
                    expect=lambda r: r["decision"] == decision,
                )
            old, new = inputs / "baseline.xml", inputs / "candidate.xml"
            old.write_text('<testsuite><testcase name="checkout"/></testsuite>', encoding="utf-8")
            new.write_text(
                '<testsuite><testcase name="checkout"><failure/></testcase></testsuite>',
                encoding="utf-8",
            )
            run(
                "25-ci-shadow",
                "ci-shadow",
                str(old),
                str(new),
                "--fail-on-change",
                code=2,
                expect=lambda r: r["changes"][0]["candidate"] == "fail",
            )

        if "platform" in enabled:
            baseline = fixture("api.json", {"repository": "api", "provides": {"orders/http": "v2"}})
            consumer = fixture(
                "client.json",
                {"repository": "client", "requires": {"orders/http": "v1"}},
            )
            run(
                "19-contract-gate",
                "repo-contract-check",
                baseline,
                consumer,
                "--fail-on-change",
                code=2,
                expect=lambda r: r["findings"][0]["reason"] == "revision_mismatch",
            )
            pilot = fixture(
                "pilot.json",
                {
                    "cases": [
                        {
                            "id": "synthetic-1",
                            "baseline_minutes": 20,
                            "assisted_minutes": 8,
                            "verification_minutes": 4,
                            "rework_minutes": 2,
                            "accepted": True,
                            "missed_critical": False,
                        }
                    ]
                },
            )
            run("20-pilot", "pilot-report", pilot, expect=lambda r: r["net_minutes_saved"] == 6)
            flags = fixture(
                "flags.json",
                {
                    "flags": {
                        "checkout": {"enabled": True, "rollout": 100, "variants": {"new": 100}},
                    }
                },
            )
            run(
                "21-feature-flag",
                "flag-evaluate",
                flags,
                "checkout",
                "--cohort",
                "synthetic",
                expect=lambda r: r["enabled"] and r["variant"] == "new",
            )
            costs = inputs / "billing.csv"
            costs.write_text(
                "BillingCurrency,BilledCost,ServiceName\nUSD,12.50,compute\n", encoding="utf-8"
            )
            run(
                "22-cost-allocation",
                "cost-report",
                str(costs),
                "--by",
                "ServiceName",
                expect=lambda r: r["totals"] == {"USD": "12.50"},
            )
            dependency = {
                "purl": "pkg:pypi/example@1.0",
                "registry": "https://approved.example",
                "sha256": "a" * 64,
            }
            approved = fixture("approved.json", {"dependencies": [dependency]})
            proposed = fixture(
                "proposed.json",
                {
                    "dependencies": [
                        {
                            **dependency,
                            "registry": "https://unapproved.example",
                        }
                    ]
                },
            )
            run(
                "26-package-provenance",
                "dependency-review",
                approved,
                proposed,
                "--fail-on-unapproved",
                code=2,
                expect=lambda r: r["findings"][0]["reason"] == "registry_mismatch",
            )

    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        summary = [
            "# RADEA Demo",
            "",
            f"Track: **{args.track}** · Offline engine · Synthetic fixtures",
            "",
            "| Report | Actual exit | Expected exit | Verification |",
            "| --- | ---: | ---: | --- |",
        ]
        for filename, actual, expected, ok, _ in rows:
            summary.append(
                f"| `{filename}` | {actual} | {expected} | {'Passed' if ok else 'Unexpected'} |"
            )
        summary += [
            "",
            "Exit 2 and 3 are expected where the demo exercises a gate or a canary hold.",
            "Download the workflow artifact for JSON reports and generated fixture files.",
        ]
        (output / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
        (output / "commands.txt").write_text(
            "\n".join(command for _, _, _, _, command in rows) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
