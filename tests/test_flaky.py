"""Flaky-test detection from several JUnit runs."""

import json

from click.testing import CliRunner

from radea.cli import main
from radea.static_review.runner import run_flaky

LIMIT = 8 * 1024 * 1024


def case(name, outcome="pass", message="", cls="pkg.T"):
    body = {
        "pass": "",
        "fail": f'<failure message="{message}">trace</failure>',
        "error": f'<error message="{message}"/>',
        "skip": "<skipped/>",
        "flaky": f'<flakyFailure message="{message}"/>',
    }[outcome]
    return f'<testcase classname="{cls}" name="{name}">{body}</testcase>'


def suite(*cases):
    joined = "".join(cases)
    return f'<?xml version="1.0"?><testsuites><testsuite name="s">{joined}</testsuite></testsuites>'


def write_runs(tmp_path, runs):
    paths = []
    for index, cases in enumerate(runs, 1):
        path = tmp_path / f"run{index:02d}.xml"
        path.write_text(suite(*cases))
        paths.append(str(path))
    return paths


def test_mixed_outcomes_are_flaky_and_constant_failures_are_broken(tmp_path):
    paths = write_runs(
        tmp_path,
        [
            [case("a", "pass"), case("b", "fail", "boom"), case("c", "pass")],
            [case("a", "fail", "Read timed out"), case("b", "fail", "boom"), case("c", "pass")],
            [case("a", "pass"), case("b", "fail", "boom"), case("c", "pass")],
            [case("a", "fail", "deadline exceeded"), case("b", "fail", "boom"), case("c", "pass")],
        ],
    )
    report = run_flaky(paths, LIMIT, 2)
    rules = {f["target"]: f for f in report["findings"]}
    assert rules["pkg.T::a"]["rule"] == "FLAKY001"
    assert "failed 2/4 runs, 3 flip(s)" in rules["pkg.T::a"]["detail"]
    assert "possible: timeout" in rules["pkg.T::a"]["detail"]
    assert rules["pkg.T::b"]["rule"] == "FLAKY002"
    assert "pkg.T::c" not in rules
    assert report["summary"]["flaky_tests"] == 1
    assert report["summary"]["consistently_failing_tests"] == 1


def test_one_run_cannot_prove_a_test_is_broken(tmp_path):
    paths = write_runs(tmp_path, [[case("a", "fail", "boom")]])
    assert run_flaky(paths, LIMIT, 2)["findings"] == []


def test_rerun_markers_count_as_flaky_even_in_one_run(tmp_path):
    paths = write_runs(tmp_path, [[case("a", "flaky", "connection refused")]])
    finding = run_flaky(paths, LIMIT, 2)["findings"][0]
    assert finding["rule"] == "FLAKY001" and "network" in finding["detail"]


def test_skipped_tests_are_ignored(tmp_path):
    paths = write_runs(tmp_path, [[case("a", "skip")], [case("a", "pass")]])
    assert run_flaky(paths, LIMIT, 2)["findings"] == []


def test_directory_runs_are_ordered_by_name(tmp_path):
    write_runs(tmp_path, [[case("a", "pass")], [case("a", "fail", "x")], [case("a", "pass")]])
    report = run_flaky([str(tmp_path)], LIMIT, 2)
    assert "2 flip(s)" in report["findings"][0]["detail"]


def test_hostile_xml_is_rejected_not_parsed(tmp_path):
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        "<testsuite><testcase classname='c' name='n'/>&b;</testsuite>"
    )
    path = tmp_path / "bomb.xml"
    path.write_text(bomb)
    report = run_flaky([str(path)], LIMIT, 2)
    assert report["summary"]["files"] == 0
    assert "DOCTYPE" in report["skipped"][0]["reason"]
    broken = tmp_path / "broken.xml"
    broken.write_text("<testsuite><testcase")
    assert run_flaky([str(broken)], LIMIT, 2)["skipped"][0]["reason"] == "not valid XML"


def test_failure_messages_are_sanitised(tmp_path):
    paths = write_runs(
        tmp_path,
        [[case("a", "pass")], [case("a", "fail", "login failed password=hunter2hunter2")]],
    )
    assert "hunter2hunter2" not in json.dumps(run_flaky(paths, LIMIT, 2))


def test_cli_exit_codes(tmp_path):
    flaky_only = write_runs(tmp_path, [[case("a", "pass")], [case("a", "fail", "x")]])
    runner = CliRunner()
    assert runner.invoke(main, ["flaky", *flaky_only]).exit_code == 0  # flaky is a warning
    assert runner.invoke(main, ["flaky", *flaky_only, "--fail-on", "medium"]).exit_code == 2
    broken_dir = tmp_path / "b"
    broken_dir.mkdir()
    write_runs(broken_dir, [[case("a", "fail", "x")], [case("a", "fail", "x")]])
    assert runner.invoke(main, ["flaky", str(broken_dir)]).exit_code == 2
