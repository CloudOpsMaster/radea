"""vuln-triage groups and ranks scanner output without changing what the scanner decided."""

import json

from click.testing import CliRunner

from radea.cli import main
from radea.static_review.runner import run_vuln

LIMIT = 8 * 1024 * 1024


def match(vid, sev, name, version, fixed=()):
    return {
        "vulnerability": {"id": vid, "severity": sev, "fix": {"versions": list(fixed)}},
        "artifact": {"name": name, "version": version},
    }


GRYPE = {
    "matches": [
        match("CVE-1", "Medium", "zlib", "1.2.11", ["1.2.12"]),
        match("CVE-2", "Critical", "openssl", "1.1.1", ["1.1.1w"]),
        match("CVE-2", "Critical", "openssl", "1.1.1", ["1.1.1w"]),  # duplicate entry
        match("CVE-3", "High", "log4j", "2.14.0"),  # high, no fix
        match("CVE-4", "High", "openssl", "1.1.1", ["3.0.0"]),
        match("CVE-5", "Low", "tzdata", "2020a", ["2021a"]),
        match("CVE-6", "Negligible", "glibc", "2.31"),
        match("CVE-7", "Unknown", "mystery", "1"),
    ]
}
TRIVY = {
    "Results": [
        {
            "Target": "app (debian 12)",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "CVE-9",
                    "PkgName": "libxml2",
                    "InstalledVersion": "2.9",
                    "FixedVersion": "2.9.1, 2.10",
                    "Severity": "HIGH",
                }
            ],
        },
        {"Target": "empty", "Vulnerabilities": None},
    ]
}


def run(tmp_path, data, minimum="medium", name="r.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return run_vuln([str(path)], LIMIT, minimum)


def test_groups_dedupes_and_ranks(tmp_path):
    report = run(tmp_path, GRYPE)
    summary = report["summary"]
    assert summary["vulnerabilities"] == 7  # CVE-2 counted once
    assert summary["packages"] == 6
    targets = [f["target"] for f in report["findings"]]
    assert targets[0] == "openssl 1.1.1"  # critical with a fix comes first
    openssl = report["findings"][0]
    assert openssl["rule"] == "VULN001" and "2 vulnerabilities" in openssl["detail"]
    assert "1.1.1w" in openssl["evidence"]
    by_target = {f["target"]: f for f in report["findings"]}
    assert by_target["log4j 2.14.0"]["rule"] == "VULN002"
    assert "no fix published" in by_target["log4j 2.14.0"]["evidence"]
    assert by_target["zlib 1.2.11"]["rule"] == "VULN003"


def test_hidden_findings_are_counted_not_dropped(tmp_path):
    summary = run(tmp_path, GRYPE, minimum="medium")["summary"]
    assert summary["not_shown_below_minimum"] == {"low": 1, "negligible": 1, "unknown": 1}
    everything = run(tmp_path, GRYPE, minimum="unknown")
    assert everything["summary"]["not_shown_below_minimum"] == {}
    assert len(everything["findings"]) == 6


def test_trivy_format_and_multiple_fix_versions(tmp_path):
    report = run(tmp_path, TRIVY)
    finding = report["findings"][0]
    assert finding["target"] == "libxml2 2.9" and finding["rule"] == "VULN001"
    assert "2.9.1" in finding["evidence"] and "2.10" in finding["evidence"]


def test_unknown_json_is_skipped_with_a_reason(tmp_path):
    report = run(tmp_path, {"hello": "world"})
    assert report["summary"]["files"] == 0
    assert "Grype or Trivy" in report["skipped"][0]["reason"]


def test_cli_gates_on_fixable_high_findings(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(GRYPE))
    runner = CliRunner()
    assert runner.invoke(main, ["vuln-triage", str(path)]).exit_code == 2
    only_unfixable = tmp_path / "u.json"
    only_unfixable.write_text(json.dumps({"matches": [match("CVE-3", "High", "log4j", "2.14.0")]}))
    assert runner.invoke(main, ["vuln-triage", str(only_unfixable)]).exit_code == 0
    assert (
        runner.invoke(main, ["vuln-triage", str(only_unfixable), "--fail-on", "medium"]).exit_code
        == 2
    )
    bad = runner.invoke(
        main, ["vuln-triage", str(path), "--output", "json", "--min-severity", "low"]
    )
    assert json.loads(bad.output)["summary"]["minimum_severity"] == "low"
