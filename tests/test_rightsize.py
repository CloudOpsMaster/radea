"""Right-sizing uses percentiles and headroom, and explains every recommendation."""

import json

from click.testing import CliRunner

from radea.cli import main
from radea.static_review.catalog import CATALOG
from radea.static_review.runner import run_rightsize

LIMIT = 8 * 1024 * 1024


def record(**over):
    base = {
        "workload": "api",
        "container": "api",
        "cpu": {"p50": 0.1, "p95": 0.4, "p99": 0.6},
        "memory": {"p50": "200Mi", "p95": "280Mi", "p99": "300Mi", "max": "320Mi"},
        "requests": {"cpu": "500m", "memory": "400Mi"},
        "limits": {"memory": "600Mi"},
    }
    base.update(over)
    return base


def run(tmp_path, *records):
    path = tmp_path / "usage.json"
    path.write_text(json.dumps(list(records)))
    return run_rightsize([str(path)], LIMIT)


def rules_in(report):
    return {f["rule"] for f in report["findings"]}


def test_well_sized_container_has_no_findings(tmp_path):
    assert run(tmp_path, record())["findings"] == []


def test_each_rule_fires(tmp_path):
    cases = {
        "RS001": record(requests={"cpu": "100m", "memory": "400Mi"}),
        "RS002": record(requests={"cpu": "500m", "memory": "100Mi"}),
        "RS003": record(limits={"memory": "330Mi"}),
        "RS004": record(requests={"cpu": "4", "memory": "400Mi"}),
    }
    for rule, rec in cases.items():
        assert rule in rules_in(run(tmp_path, rec)), rule
    assert set(cases) == {k for k in CATALOG if k.startswith("RS")}


def test_recommendation_is_derived_from_percentiles_not_averages(tmp_path):
    report = run(tmp_path, record())
    recommendation = report["summary"]["recommendations"][0]
    assert recommendation["cpu_request"] == "460m"  # p95 0.4 x 1.15
    assert recommendation["memory_request"] == "368Mi"  # p99 300Mi x 1.2 rounded to 16Mi
    assert recommendation["memory_limit"] == "416Mi"  # max 320Mi x 1.3 rounded to 16Mi
    assert "p95" in recommendation["basis"]


def test_burst_is_not_hidden_by_a_low_average(tmp_path):
    spiky = record(
        cpu={"p50": 0.01, "p95": 0.9, "p99": 1.5}, requests={"cpu": "50m", "memory": "400Mi"}
    )
    finding = next(f for f in run(tmp_path, spiky)["findings"] if f["rule"] == "RS001")
    assert "p95 900m" in finding["evidence"] and "recommend 1040m" in finding["detail"]


def test_small_differences_are_not_called_over_provisioned(tmp_path):
    rec = record(cpu={"p95": 0.01}, requests={"cpu": "50m", "memory": "400Mi"})
    assert "RS004" not in rules_in(run(tmp_path, rec))


def test_incomplete_or_inconsistent_records_are_skipped_with_a_reason(tmp_path):
    report = run(
        tmp_path,
        {"workload": "x", "container": "y"},
        record(memory={"p99": "500Mi", "max": "100Mi"}),
    )
    assert report["findings"] == []
    assert len(report["skipped"]) == 2 and "incomplete usage" in report["skipped"][0]["reason"]


def test_cli(tmp_path):
    path = tmp_path / "u.json"
    path.write_text(json.dumps([record(requests={"cpu": "100m", "memory": "100Mi"})]))
    runner = CliRunner()
    assert runner.invoke(main, ["rightsize", str(path)]).exit_code == 2  # RS002 is high
    assert runner.invoke(main, ["rightsize", str(path), "--fail-on", "never"]).exit_code == 0
    path.write_text("{}")
    assert runner.invoke(main, ["rightsize", str(path)]).exit_code == 1
