"""test-review finds tests that cannot fail, without flagging the usual safe shapes."""

import json
import textwrap

import pytest
from click.testing import CliRunner

from radea.cli import main
from radea.static_review.catalog import CATALOG
from radea.static_review.runner import run_tests

LIMIT = 8 * 1024 * 1024


def review(tmp_path, text, name="test_x.py"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(text))
    return run_tests([str(path)], LIMIT)


def rules(report):
    return {f["rule"] for f in report["findings"]}


PY_CASES = {
    "TEST001": "def test_a():\n    x = 1 + 1\n",
    "TEST002": "def test_a():\n    assert True\n",
    "TEST003": "def test_a():\n    pass\n",
    "TEST004": "def test_a():\n    try:\n        f()\n    except Exception:\n        pass\n",
}
JAVA_CASES = {
    "TEST001": "class T {\n  @Test\n  void a() {\n    run();\n  }\n}\n",
    "TEST002": "class T {\n  @Test\n  void a() {\n    assertTrue(true);\n  }\n}\n",
    "TEST003": "class T {\n  @Test\n  void a() {\n  }\n}\n",
    "TEST004": (
        "class T {\n  @Test\n  void a() {\n    try { run(); } catch (Exception e) {}\n  }\n}\n"
    ),
}


@pytest.mark.parametrize("rule", sorted(PY_CASES))
def test_python_rules_fire(tmp_path, rule):
    assert rule in rules(review(tmp_path, PY_CASES[rule])), rule


@pytest.mark.parametrize("rule", sorted(JAVA_CASES))
def test_java_rules_fire(tmp_path, rule):
    assert rule in rules(review(tmp_path, JAVA_CASES[rule], "ATest.java")), rule


def test_every_test_rule_has_a_case():
    assert set(PY_CASES) == {k for k in CATALOG if k.startswith("TEST")}


@pytest.mark.parametrize(
    "text",
    [
        "def test_a():\n    assert f() == 3\n",
        "def test_a():\n    with pytest.raises(ValueError):\n        f()\n",
        "def test_a():\n    check_total(f())\n",
        "def test_a(mocker):\n    m = mocker.Mock()\n    m.run()\n    m.run.assert_called_once()\n",
        "class TestA(unittest.TestCase):\n    def test_a(self):\n"
        "        self.assertEqual(f(), 3)\n",
        "def test_a():  # radea: allow-no-assert\n    f()\n",
        "@pytest.mark.skip(reason='x')\ndef test_a():\n    pass\n",
        "@pytest.mark.xfail\ndef test_a():\n    f()\n",
        "def helper():\n    f()\n",  # not a test
        "def test_a():\n    try:\n        f()\n    except ValueError:\n        pass\n"
        "    assert 1 == f()\n",
        "async def test_a():\n    assert await f() == 1\n",
        "def test_a():\n    '''doc'''\n    assert f(), 'message'\n",
        "def test_a():\n    wait_and_assert_ready()\n",
        "def test_a():\n    client.verify_called(3)\n",
        "def test_a():\n    approx = pytest.approx(0.1)\n    assert 0.1 + 0.2 == approx\n",
    ],
)
def test_safe_python_shapes_are_not_flagged(tmp_path, text):
    assert rules(review(tmp_path, text)) == set(), text


@pytest.mark.parametrize(
    "text",
    [
        "class T {\n  @Test void a() { assertEquals(3, run()); }\n}\n",
        "class T {\n  @Test void a() { verify(mock).run(); }\n}\n",
        "class T {\n  @Test void a() { assertThrows(X.class, () -> run()); }\n}\n",
        "class T {\n  @Test(expected = X.class)\n  void a() { run(); }\n}\n",
        "class T {\n  @Disabled\n  @Test\n  void a() { run(); }\n}\n",
        'class T {\n  @Test void a() { mvc.perform(get("/")).andExpect(status().isOk()); }\n}\n',
        "class T {\n  @Test void a() { assertThat(run()).isEqualTo(3); }\n}\n",
        "class T {\n  void helper() { run(); }\n}\n",
        "class T {\n  @Test void a() { ext.waitAndAssertCounter(M, 3, 80); }\n}\n",
        "class T {\n  @Test void a() {\n    // radea: allow-no-assert\n    run();\n  }\n}\n",
        "class T {\n  @Test void a() {\n"
        '    String s = "} assertEquals(1, 1) {";\n'
        "    assertEquals(2, run());\n  }\n}\n",
    ],
)
def test_safe_java_shapes_are_not_flagged(tmp_path, text):
    assert rules(review(tmp_path, text, "ATest.java")) == set(), text


def test_assertions_inside_comments_and_strings_do_not_count(tmp_path):
    text = (
        "class T {\n  @Test void a() {\n    // assertEquals(1, 1);\n"
        '    String s = "assertTrue(x)";\n'
        "    run();\n  }\n}\n"
    )
    assert "TEST001" in rules(review(tmp_path, text, "ATest.java"))


def test_kotlin_backtick_names_and_line_numbers(tmp_path):
    text = "class T {\n    @Test\n    fun `does nothing useful`() {\n        run()\n    }\n}\n"
    report = review(tmp_path, text, "ATest.kt")
    finding = report["findings"][0]
    assert finding["rule"] == "TEST001" and finding["target"] == "does nothing useful"
    assert finding["line"] == 3


def test_python_line_numbers_and_targets(tmp_path):
    report = review(tmp_path, "import x\n\n\ndef test_the_thing():\n    f()\n")
    finding = report["findings"][0]
    assert (finding["target"], finding["line"]) == ("test_the_thing", 4)
    assert "def test_the_thing" in finding["evidence"]


def test_invalid_python_is_skipped_with_a_reason(tmp_path):
    report = review(tmp_path, "def test_a(:\n")
    assert report["summary"]["files"] == 0 and report["skipped"][0]["reason"] == "not valid Python"


def test_directory_walk_only_reads_test_files(tmp_path):
    (tmp_path / "test_a.py").write_text("def test_a():\n    f()\n")
    (tmp_path / "helpers.py").write_text("def test_looking_helper():\n    f()\n")
    (tmp_path / "BTest.java").write_text(JAVA_CASES["TEST001"])
    (tmp_path / "Plain.java").write_text(JAVA_CASES["TEST001"])
    report = run_tests([str(tmp_path)], LIMIT)
    assert sorted(s["path"].rsplit("/", 1)[-1] for s in report["sources"]) == [
        "BTest.java",
        "test_a.py",
    ]


def test_examples_and_cli(tmp_path):
    assert (
        run_tests(["examples/tests/good.py", "examples/tests/GoodTest.java"], LIMIT)["findings"]
        == []
    )
    bad = run_tests(["examples/tests/bad.py", "examples/tests/BadTest.java"], LIMIT)
    assert rules(bad) == {"TEST001", "TEST002", "TEST003", "TEST004"}
    runner = CliRunner()
    assert runner.invoke(main, ["test-review", "examples/tests/good.py"]).exit_code == 0
    assert (
        runner.invoke(
            main, ["test-review", "examples/tests/bad.py", "--fail-on", "medium"]
        ).exit_code
        == 2
    )
    assert (
        runner.invoke(main, ["test-review", "examples/tests/bad.py"]).exit_code == 0
    )  # medium < high
    result = runner.invoke(main, ["test-review", "examples/tests/bad.py", "--output", "json"])
    assert json.loads(result.output)["summary"]["by_severity"]["medium"] >= 3
    assert runner.invoke(main, ["test-review", str(tmp_path)]).exit_code == 1


def test_python_truthy_and_falsy_constants_are_trivial(tmp_path):
    text = (
        "import unittest\nclass TestA(unittest.TestCase):\n    def test_a(self):\n"
        "        self.assertTrue('False')\n        self.assertFalse('')\n"
        "        self.assertEqual(f(), f())\n"
    )
    findings = review(tmp_path, text)["findings"]
    assert [f["rule"] for f in findings] == ["TEST002"] * 3


def test_helper_only_tests_name_the_helper_they_call(tmp_path):
    report = review(tmp_path, "def test_a():\n    LogUtils.check_logs_exist(1)\n    other()\n")
    # check_* counts as an assertion helper, so use a neutral name for the helper-only case
    assert report["findings"] == []
    report = review(tmp_path, "def test_a():\n    logs_exist(1)\n")
    assert report["findings"][0]["detail"] == "calls logs_exist()"
    java = "class T {\n  @Test void a() {\n    LogUtils.logsExist(1);\n  }\n}\n"
    assert (
        review(tmp_path, java, "ATest.java")["findings"][0]["detail"]
        == "calls LogUtils.logsExist()"
    )
